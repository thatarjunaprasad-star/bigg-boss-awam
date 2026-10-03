"""Bigg Boss Awam — central configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("AWAM_DATA_DIR", BASE_DIR / "data"))
FRONTEND_DIR = Path(os.environ.get("AWAM_FRONTEND_DIR", BASE_DIR.parent / "frontend"))


@dataclass
class Settings:
    app_name: str = "Bigg Boss Awam"
    tagline: str = "The People's Oracle — Unofficial Bigg Boss Intelligence"
    version: str = "1.0.0"

    host: str = os.environ.get("AWAM_HOST", "127.0.0.1")
    port: int = int(os.environ.get("AWAM_PORT", "8000"))

    db_path: Path = DATA_DIR / "awam.db"

    # ---- Inference engine -------------------------------------------------
    # Optional OpenAI-compatible endpoint (vLLM / llama.cpp server on ROCm,
    # LM Studio, etc.). When unset, the built-in local engine is used.
    llm_base_url: str = os.environ.get("AWAM_LLM_BASE_URL", "")
    llm_model: str = os.environ.get("AWAM_LLM_MODEL", "awam-local")
    llm_timeout_s: float = float(os.environ.get("AWAM_LLM_TIMEOUT", "20"))

    # Paged KV cache geometry (vLLM-style block accounting)
    kv_num_blocks: int = int(os.environ.get("AWAM_KV_NUM_BLOCKS", "4096"))
    kv_block_size: int = int(os.environ.get("AWAM_KV_BLOCK_SIZE", "16"))
    kv_max_session_tokens: int = int(os.environ.get("AWAM_KV_MAX_SESSION_TOKENS", "1024"))

    # One vote per session key per 24h window
    vote_cooldown_hours: int = 24

    default_profile: str = os.environ.get("AWAM_PROFILE", "balanced")

    telemetry_window: int = 512

    extra: dict = field(default_factory=dict)


settings = Settings()
