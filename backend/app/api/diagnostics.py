"""Diagnostics routes — the Engine Room."""
from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Request

from ..runtime import Runtime
from .deps import get_runtime

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("")
def diagnostics(request: Request):
    runtime: Runtime = get_runtime(request)
    return {
        "app": {
            "name": runtime.settings.app_name,
            "version": runtime.settings.version,
            "tagline": runtime.settings.tagline,
        },
        "device": runtime.device.as_dict(),
        "engine": runtime.engine.engine_info(),
        "profile": {
            "active": runtime.tuner.active_profile.key,
            "label": runtime.tuner.active_profile.label,
            "description": runtime.tuner.active_profile.description,
            "attention_backend": runtime.tuner.active_profile.attention_backend,
            "dtype": runtime.tuner.active_profile.dtype,
        },
        "profiles": runtime.tuner.available_profiles(),
        "kv_cache": runtime.kv_cache.stats().__dict__,
        "telemetry": runtime.telemetry.overview(),
        "latency_series": runtime.telemetry.recent_series(120),
        "data": runtime.db.stats(),
        "last_benchmark": runtime.tuner.last_benchmark.as_dict() if runtime.tuner.last_benchmark else None,
    }


class ProfileRequest(BaseModel):
    profile: str


@router.post("/profile")
def set_profile(body: ProfileRequest, request: Request):
    runtime: Runtime = get_runtime(request)
    try:
        profile = runtime.tuner.set_profile(body.profile)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "applied",
        "active": profile.key,
        "label": profile.label,
        "profiles": runtime.tuner.available_profiles(),
    }


@router.post("/benchmark")
def benchmark(request: Request):
    runtime: Runtime = get_runtime(request)

    def local_synth(text: str) -> str:
        return runtime.agent.respond("diagnostics-bench", text)[0]

    result = runtime.tuner.benchmark(local_synth=local_synth)
    runtime.telemetry.record_latency("benchmark", 0.0)
    return {"benchmark": result.as_dict()}
