"""Chat route — the conversational interface to the Awam agent."""
from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Request

from ..runtime import Runtime
from .deps import get_runtime, session_key

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


@router.post("")
def chat(body: ChatRequest, request: Request):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, body.session_id)
    result = runtime.engine.generate(sid, body.message)

    runtime.telemetry.record_latency("chat", result.latency_ms)
    runtime.telemetry.bump("chat_messages")
    runtime.telemetry.add_tokens(result.tokens_in, result.tokens_out, result.latency_ms)

    return {
        "session_id": sid,
        "reply": result.reply,
        "intent": result.intent,
        "meta": {
            "engine": result.engine,
            "model": result.model,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "tokens_per_sec": result.tokens_per_sec,
            "ttft_ms": result.ttft_ms,
            "latency_ms": result.latency_ms,
            "cache_hit_rate_pct": result.cache_hit_rate_pct,
            "context_tokens": result.context_tokens,
            "cached_prefix_tokens": result.cached_prefix_tokens,
            "evicted_sessions": result.evicted_sessions,
            "remote_error": result.remote_error,
        },
    }


@router.get("/history")
def history(request: Request, session_id: str = ""):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, session_id)
    return {"session_id": sid, "turns": runtime.engine.history(sid)}
