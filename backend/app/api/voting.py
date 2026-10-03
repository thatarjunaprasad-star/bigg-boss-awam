"""Voting & ratings routes."""
from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request

from ..data.db import VoteResult
from ..runtime import Runtime
from .deps import get_runtime, session_key

router = APIRouter(prefix="/api", tags=["voting"])


class VoteRequest(BaseModel):
    contestant_id: int
    session_key: str | None = None


class RateRequest(BaseModel):
    contestant_id: int
    stars: int = Field(ge=1, le=5)
    session_key: str | None = None


@router.get("/contestants")
def contestants(request: Request):
    runtime: Runtime = get_runtime(request)
    return {
        "contestants": runtime.db.contestants(),
        "total_votes": runtime.db.total_votes(),
    }


@router.get("/leaderboard")
def leaderboard(request: Request):
    runtime: Runtime = get_runtime(request)
    return {"leaderboard": runtime.db.contestants()}


@router.post("/vote")
def vote(body: VoteRequest, request: Request):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, body.session_key)
    result = runtime.db.cast_vote(sid, body.contestant_id, runtime.settings.vote_cooldown_hours)
    if result.status == VoteResult.CAST:
        runtime.telemetry.bump("votes")
    return {
        "status": result.status,
        "detail": result.detail,
        "contestant": result.contestant,
        "voted_today": runtime.db.vote_today(sid, runtime.settings.vote_cooldown_hours),
    }


@router.post("/rate")
def rate(body: RateRequest, request: Request):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, body.session_key)
    updated = runtime.db.rate(sid, body.contestant_id, body.stars)
    if updated is None:
        raise HTTPException(status_code=404, detail="Contestant not found")
    runtime.telemetry.bump("ratings")
    return {"status": "rated", "contestant": updated, "your_stars": body.stars}


@router.get("/vote-status")
def vote_status(request: Request, session_key_value: str = ""):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, session_key_value)
    return {
        "session_key": sid,
        "voted_today": runtime.db.vote_today(sid, runtime.settings.vote_cooldown_hours),
        "rated": runtime.db.rated_by_session(sid),
    }
