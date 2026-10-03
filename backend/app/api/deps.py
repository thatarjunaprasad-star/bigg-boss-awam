"""Shared API helpers."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import Request

from ..runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def session_key(request: Request, body_value: Optional[str] = None) -> str:
    """Session identity: header first, then body, else a fresh anonymous key."""
    header = request.headers.get("x-awam-session", "").strip()
    key = header or (body_value or "").strip()
    if not key:
        return f"anon-{uuid.uuid4().hex[:12]}"
    return key[:64]


def contestant_public(c: dict[str, Any]) -> dict[str, Any]:
    return c
