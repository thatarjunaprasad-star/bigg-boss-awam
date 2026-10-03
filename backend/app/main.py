"""Bigg Boss Awam — FastAPI application assembly."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import chat, content, diagnostics, voting
from .core.config import FRONTEND_DIR, settings
from .runtime import build_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = build_runtime(settings)
    app.state.runtime = runtime
    device = runtime.device
    print()
    print("=" * 62)
    print(f"  👁  {settings.app_name.upper()} v{settings.version}")
    print(f"      {settings.tagline}")
    print("=" * 62)
    print(f"  Device      : {device.label}")
    if device.rocm_version:
        print(f"  ROCm        : {device.rocm_version}")
    print(f"  Engine      : AwamInfer 1.0.0 · profile '{runtime.tuner.active_profile.label}'")
    print(f"  KV cache    : {settings.kv_num_blocks} blocks × {settings.kv_block_size} tokens/block")
    print(f"  LLM endpoint: {settings.llm_base_url or 'built-in local synthesis'}")
    for note in device.notes:
        print(f"  · {note}")
    print("=" * 62)
    yield
    runtime.db.close()


app = FastAPI(
    title="Bigg Boss Awam",
    description="Unofficial Bigg Boss AI agent — votings, ratings, news & trivia, "
                "powered by the AwamInfer engine (ROCm-ready).",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        if hasattr(request.app.state, "runtime"):
            request.app.state.runtime.telemetry.record_error()
        raise
    if request.url.path.startswith("/api/"):
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            runtime.telemetry.bump("requests")
            runtime.telemetry.record_latency(
                request.url.path.split("?")[0], (time.perf_counter() - start) * 1000
            )
    return response


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


app.include_router(chat.router)
app.include_router(voting.router)
app.include_router(content.router)
app.include_router(diagnostics.router)

if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    def missing_frontend():
        return JSONResponse(
            status_code=503,
            content={"detail": "Frontend directory not found. Expected at: " + str(FRONTEND_DIR)},
        )
