"""News feed & trivia routes."""
from __future__ import annotations

import re

from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Request

from ..runtime import Runtime
from .deps import get_runtime, session_key

router = APIRouter(prefix="/api", tags=["content"])


@router.get("/news")
def news(request: Request, limit: int = 20):
    runtime: Runtime = get_runtime(request)
    limit = max(1, min(limit, 50))
    return {"news": runtime.db.latest_news(limit)}


@router.get("/trivia/next")
def trivia_next(request: Request):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request)
    question = runtime.db.next_trivia(sid)
    if question is None:
        raise HTTPException(status_code=404, detail="Trivia vault is empty")
    return {"question": question, "score": runtime.db.trivia_score(sid)}


class TriviaAnswerRequest(BaseModel):
    trivia_id: int
    choice: str
    session_key: str | None = None


@router.post("/trivia/answer")
def trivia_answer(body: TriviaAnswerRequest, request: Request):
    runtime: Runtime = get_runtime(request)
    sid = session_key(request, body.session_key)

    question = runtime.db.trivia_by_id(body.trivia_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question")

    letter = body.choice.strip().lower()
    match = re.fullmatch(r"(?:option\s*)?([a-d1-4])[).:]?", letter)
    if not match:
        raise HTTPException(status_code=400, detail="Choice must be A, B, C or D")
    token = match.group(1)
    idx = "abcd".index(token) if token.isalpha() else int(token) - 1
    if idx >= len(question["options"]):
        raise HTTPException(status_code=400, detail="Choice out of range")

    correct_idx = question["answer_idx"]
    is_correct = idx == correct_idx
    runtime.db.record_trivia(sid, question["id"], is_correct)
    runtime.telemetry.bump("trivia_answers")
    if is_correct:
        runtime.telemetry.bump("trivia_correct")

    return {
        "correct": is_correct,
        "your_option": question["options"][idx],
        "correct_option": question["options"][correct_idx],
        "correct_letter": "ABCD"[correct_idx],
        "fun_fact": question["fun_fact"],
        "score": runtime.db.trivia_score(sid),
    }
