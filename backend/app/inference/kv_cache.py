"""Paged KV cache manager — vLLM-style block accounting in miniature.

Each session's token history is paged into fixed-size blocks drawn from a
global pool. Appending to a session is a *cache hit* for the prefix that is
still resident (no recompute needed — exactly how paged attention reuses
context between turns) and a *miss* only for the newly generated tokens.

Pressure handling mirrors production engines:
  * A session that outgrows its window slides (its oldest blocks are freed).
  * When the global pool is exhausted, the least-recently-used *other* session
    is evicted wholesale; its next turn starts cold.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict


@dataclass
class AppendResult:
    cached_prefix_tokens: int   # tokens already resident (cache hits)
    appended_tokens: int        # tokens newly written (cache misses)
    resident_tokens: int        # tokens resident after the append
    evicted_sessions: list[str] = field(default_factory=list)
    slid_blocks: int = 0        # own oldest blocks freed by window slide
    new_blocks: int = 0         # fresh blocks allocated


@dataclass
class CacheStats:
    capacity_blocks: int
    block_size: int
    used_blocks: int
    utilization_pct: float
    active_sessions: int
    tokens_cached: int
    hits: int
    misses: int
    hit_rate_pct: float
    evicted_sessions: int
    slid_blocks: int
    peak_utilization_pct: float


class _SessionState:
    __slots__ = ("tokens", "blocks", "last_access")

    def __init__(self) -> None:
        self.tokens: Deque[int] = deque()
        self.blocks: int = 0
        self.last_access: int = 0  # monotonic tick; wall-clock ties break LRU ordering


class PagedKVCacheManager:
    def __init__(self, num_blocks: int = 4096, block_size: int = 16,
                 max_session_tokens: int = 1024) -> None:
        self.num_blocks = num_blocks
        self.block_size = block_size
        self.max_session_tokens = max(2 * block_size, max_session_tokens)
        self._lock = threading.RLock()
        self._sessions: Dict[str, _SessionState] = {}
        self._tick = 0
        self._hits = 0
        self._misses = 0
        self._evicted_sessions = 0
        self._slid_blocks = 0
        self._peak_blocks = 0

    # ------------------------------------------------------------------ public
    def append(self, session_id: str, token_ids: list[int]) -> AppendResult:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = _SessionState()
                self._sessions[session_id] = state
            self._tick += 1
            state.last_access = self._tick

            cached_prefix = min(len(state.tokens), self.max_session_tokens)
            self._hits += cached_prefix
            self._misses += len(token_ids)

            state.tokens.extend(token_ids)

            slid = 0
            if len(state.tokens) > self.max_session_tokens:
                overflow_tokens = len(state.tokens) - self.max_session_tokens
                for _ in range(overflow_tokens):
                    state.tokens.popleft()
                slid = (overflow_tokens + self.block_size - 1) // self.block_size
                self._slid_blocks += slid

            needed = (len(state.tokens) + self.block_size - 1) // self.block_size
            state.blocks = needed

            evicted: list[str] = []
            self._ensure_capacity(evicted, keep=session_id)

            self._peak_blocks = max(self._peak_blocks, self._used_blocks())

            return AppendResult(
                cached_prefix_tokens=cached_prefix,
                appended_tokens=len(token_ids),
                resident_tokens=len(state.tokens),
                evicted_sessions=evicted,
                slid_blocks=slid,
                new_blocks=max(0, needed - cached_prefix // self.block_size),
            )

    def resident(self, session_id: str) -> int:
        """Number of most-recent tokens still cached for a session (0 if evicted)."""
        with self._lock:
            state = self._sessions.get(session_id)
            return len(state.tokens) if state else 0

    def drop_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def stats(self) -> CacheStats:
        with self._lock:
            used = self._used_blocks()
            total_tokens = sum(len(s.tokens) for s in self._sessions.values())
            lookups = self._hits + self._misses
            return CacheStats(
                capacity_blocks=self.num_blocks,
                block_size=self.block_size,
                used_blocks=used,
                utilization_pct=round(used / self.num_blocks * 100, 1),
                active_sessions=len(self._sessions),
                tokens_cached=total_tokens,
                hits=self._hits,
                misses=self._misses,
                hit_rate_pct=round(self._hits / lookups * 100, 1) if lookups else 0.0,
                evicted_sessions=self._evicted_sessions,
                slid_blocks=self._slid_blocks,
                peak_utilization_pct=round(self._peak_blocks / self.num_blocks * 100, 1),
            )

    def reset_metrics(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evicted_sessions = 0
            self._slid_blocks = 0
            self._peak_blocks = self._used_blocks()

    # ---------------------------------------------------------------- internal
    def _used_blocks(self) -> int:
        return sum(s.blocks for s in self._sessions.values())

    def _ensure_capacity(self, evicted: list[str], keep: str | None = None) -> None:
        while self._used_blocks() > self.num_blocks:
            victim = self._pick_lru_victim(keep)
            if victim is None:
                break
            self._sessions.pop(victim)
            self._evicted_sessions += 1
            evicted.append(victim)

    def _pick_lru_victim(self, keep: str | None = None) -> str | None:
        candidates = [
            (s.last_access, sid)
            for sid, s in self._sessions.items()
            if s.blocks > 0 and sid != keep
        ]
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]
