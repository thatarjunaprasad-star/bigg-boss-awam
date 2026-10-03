"""AwamInfer — the high-performance inference engine facade.

Pipeline per request:
  1. tokenize the user turn (misses) → paged KV cache append
  2. context window = whatever of this session's history is still resident
  3. generation: remote OpenAI-compatible endpoint when configured (e.g. a
     vLLM server on an AMD GPU via ROCm), else the built-in local synthesizer
  4. tokenize the reply → cache append (prompt + completion, like a real engine)
  5. emit per-request telemetry (TTFT, tokens/sec, cache hit rate)
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Optional

from .device import DeviceInfo
from .kv_cache import PagedKVCacheManager
from .tokenizer import count_tokens, tokenize
from .tuner import TorchTuner


@dataclass
class GenerationResult:
    reply: str
    intent: str
    engine: str                      # "remote-llm" | "awam-local"
    model: str
    tokens_in: int
    tokens_out: int
    cached_prefix_tokens: int
    context_tokens: int
    latency_ms: float
    ttft_ms: float
    tokens_per_sec: float
    cache_hit_rate_pct: float
    evicted_sessions: list[str] = field(default_factory=list)
    remote_error: str = ""


class _Session:
    __slots__ = ("turns", "created_at")

    def __init__(self) -> None:
        self.turns: Deque[tuple[str, str]] = deque(maxlen=60)
        self.created_at = time.time()


class AwamInferEngine:
    def __init__(
        self,
        local_synth: Callable[..., tuple[str, str]],
        device_info: DeviceInfo,
        kv_cache: PagedKVCacheManager,
        tuner: TorchTuner,
        llm_base_url: str = "",
        llm_model: str = "awam-local",
        llm_timeout_s: float = 20.0,
        system_prompt_builder: Optional[Callable[[], str]] = None,
        max_history_turns: int = 12,
    ) -> None:
        self._local_synth = local_synth
        self.device_info = device_info
        self.kv_cache = kv_cache
        self.tuner = tuner
        self._llm_base_url = llm_base_url.rstrip("/")
        self._llm_model = llm_model
        self._llm_timeout_s = llm_timeout_s
        self._system_prompt_builder = system_prompt_builder or (lambda: "")
        self._max_history_turns = max_history_turns
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def generate(self, session_id: str, user_text: str) -> GenerationResult:
        session = self._get_session(session_id)

        t_start = time.perf_counter()
        user_ids = [t.id for t in tokenize(user_text)]
        append_in = self.kv_cache.append(session_id, user_ids)
        context_tokens = append_in.resident_tokens

        reply, intent, engine_used, model, remote_error = self._generate_reply(
            session, session_id, user_text
        )

        reply_ids = [t.id for t in tokenize(reply)]
        append_out = self.kv_cache.append(session_id, reply_ids)

        session.turns.append(("user", user_text))
        session.turns.append(("assistant", reply))

        latency_ms = (time.perf_counter() - t_start) * 1000
        tokens_in = len(user_ids)
        tokens_out = len(reply_ids)
        gen_seconds = max(latency_ms / 1000.0, 1e-9)
        stats = self.kv_cache.stats()

        return GenerationResult(
            reply=reply,
            intent=intent,
            engine=engine_used,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_prefix_tokens=append_in.cached_prefix_tokens,
            context_tokens=context_tokens,
            latency_ms=round(latency_ms, 1),
            ttft_ms=round(latency_ms, 1),
            tokens_per_sec=round(tokens_out / gen_seconds, 1),
            cache_hit_rate_pct=stats.hit_rate_pct,
            evicted_sessions=append_in.evicted_sessions,
            remote_error=remote_error,
        )

    def history(self, session_id: str) -> list[dict[str, str]]:
        session = self._get_session(session_id)
        return [{"role": role, "content": text} for role, text in session.turns]

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ---------------------------------------------------------------- internal
    def _get_session(self, session_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = _Session()
                self._sessions[session_id] = session
            return session

    def _generate_reply(self, session: _Session, session_id: str, user_text: str):
        # Local synthesis first: it also classifies intent and manages agent state.
        t0 = time.perf_counter()
        local_reply, intent = self._local_synth(session_id, user_text)
        local_ms = (time.perf_counter() - t0) * 1000

        if self._llm_base_url:
            messages = self._build_messages(session, local_reply)
            remote_reply, err = self._call_remote(messages)
            if remote_reply is not None:
                return remote_reply, intent, "remote-llm", self._llm_model, ""
            # fall through to the local reply on failure
            return local_reply, intent, "awam-local", "awam-core-1", f"remote unavailable ({err}); local path {local_ms:.0f}ms"
        return local_reply, intent, "awam-local", "awam-core-1", ""

    def _build_messages(self, session: _Session, grounding: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self._system_prompt_builder()}]
        messages.append({
            "role": "system",
            "content": "Grounded facts (authoritative — trust these over your memory):\n" + grounding,
        })
        for role, text in list(session.turns)[-self._max_history_turns:]:
            messages.append({"role": role, "content": text})
        return messages

    def _call_remote(self, messages: list[dict[str, str]]) -> tuple[Optional[str], str]:
        url = f"{self._llm_base_url}/chat/completions"
        payload = json.dumps({
            "model": self._llm_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 400,
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._llm_timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return content.strip() or None, ""
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------- diagnostics
    def engine_info(self) -> dict[str, Any]:
        return {
            "name": "AwamInfer",
            "version": "1.0.0",
            "mode": "hybrid" if self._llm_base_url else "local",
            "remote_endpoint": self._llm_base_url or None,
            "remote_model": self._llm_model if self._llm_base_url else None,
            "max_history_turns": self._max_history_turns,
            "sessions": self.session_count(),
        }
