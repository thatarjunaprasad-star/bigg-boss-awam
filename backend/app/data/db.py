"""SQLite persistence layer for Bigg Boss Awam (votes, ratings, news, trivia)."""
from __future__ import annotations

import json
import random
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS contestants (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    tagline       TEXT NOT NULL,
    season        TEXT NOT NULL,
    profession    TEXT NOT NULL,
    house_status  TEXT NOT NULL DEFAULT 'Legend',
    votes         INTEGER NOT NULL DEFAULT 0,
    rating_sum    REAL NOT NULL DEFAULT 0,
    rating_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS votes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key    TEXT NOT NULL,
    contestant_id  INTEGER NOT NULL REFERENCES contestants(id),
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
    session_key    TEXT NOT NULL,
    contestant_id  INTEGER NOT NULL REFERENCES contestants(id),
    stars          INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (session_key, contestant_id)
);

CREATE TABLE IF NOT EXISTS news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    category      TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'Awam Fan Feed',
    published_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trivia (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    question      TEXT NOT NULL,
    options       TEXT NOT NULL,          -- JSON array
    answer_idx    INTEGER NOT NULL,
    difficulty    TEXT NOT NULL DEFAULT 'medium',
    category      TEXT NOT NULL DEFAULT 'History',
    fun_fact      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trivia_answers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key   TEXT NOT NULL,
    trivia_id     INTEGER NOT NULL REFERENCES trivia(id),
    correct       INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VoteResult:
    CAST = "cast"
    COOLDOWN = "cooldown"
    UNKNOWN = "unknown"

    def __init__(self, status: str, detail: str = "", contestant: Optional[dict] = None,
                 next_vote_in_hours: float = 0.0) -> None:
        self.status = status
        self.detail = detail
        self.contestant = contestant
        self.next_vote_in_hours = next_vote_in_hours


class Database:
    """Single-connection SQLite store, serialized by a re-entrant lock."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- contestants ---------------------------------------------------------
    def contestants(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM contestants ORDER BY votes DESC, name ASC"
            ).fetchall()
        total = sum(r["votes"] for r in rows) or 1
        out = []
        for rank, r in enumerate(rows, start=1):
            out.append({
                "id": r["id"],
                "name": r["name"],
                "tagline": r["tagline"],
                "season": r["season"],
                "profession": r["profession"],
                "house_status": r["house_status"],
                "votes": r["votes"],
                "rank": rank,
                "vote_share_pct": round(r["votes"] / total * 100, 1),
                "rating_avg": round(r["rating_sum"] / r["rating_count"], 2) if r["rating_count"] else 0.0,
                "rating_count": r["rating_count"],
            })
        return out

    def contestant(self, contestant_id: int) -> Optional[dict[str, Any]]:
        for c in self.contestants():
            if c["id"] == contestant_id:
                return c
        return None

    def find_contestant(self, query: str) -> Optional[dict[str, Any]]:
        """Fuzzy lookup by name — supports first names, full names, close matches."""
        import difflib

        names = {c["name"]: c for c in self.contestants()}
        q = query.strip().lower()
        if not q:
            return None
        for name, c in names.items():
            if q == name.lower():
                return c
        for name, c in names.items():
            if q in name.lower():
                return c
        first_names = {name.split()[0].lower(): c for name, c in names.items()}
        for token in q.replace(",", " ").split():
            if token in first_names:
                return first_names[token]
        close = difflib.get_close_matches(q, [n.lower() for n in names], n=1, cutoff=0.6)
        if close:
            return names[[n for n in names if n.lower() == close[0]][0]]
        return None

    # -- voting ----------------------------------------------------------------
    def cast_vote(self, session_key: str, contestant_id: int, cooldown_hours: int = 24) -> VoteResult:
        with self._lock:
            contestant = self._row("SELECT * FROM contestants WHERE id = ?", (contestant_id,))
            if contestant is None:
                return VoteResult(VoteResult.UNKNOWN, "No such contestant.")
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
            recent = self._conn.execute(
                "SELECT contestant_id, created_at FROM votes WHERE session_key = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT 1",
                (session_key, cutoff),
            ).fetchone()
            if recent is not None:
                voted_for = self._conn.execute(
                    "SELECT name FROM contestants WHERE id = ?", (recent["contestant_id"],)
                ).fetchone()["name"]
                return VoteResult(
                    VoteResult.COOLDOWN,
                    f"Vote already cast for {voted_for} in the last {cooldown_hours}h.",
                    next_vote_in_hours=cooldown_hours,
                )
            self._conn.execute(
                "INSERT INTO votes (session_key, contestant_id, created_at) VALUES (?, ?, ?)",
                (session_key, contestant_id, _utcnow()),
            )
            self._conn.execute(
                "UPDATE contestants SET votes = votes + 1 WHERE id = ?", (contestant_id,)
            )
            self._conn.commit()
        return VoteResult(VoteResult.CAST, "Vote recorded.", self.contestant(contestant_id))

    def vote_today(self, session_key: str, cooldown_hours: int = 24) -> Optional[dict[str, Any]]:
        """Contestant this session voted for within the cooldown window, if any."""
        with self._lock:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
            row = self._conn.execute(
                "SELECT c.name, c.id FROM votes v JOIN contestants c ON c.id = v.contestant_id "
                "WHERE v.session_key = ? AND v.created_at >= ? ORDER BY v.created_at DESC LIMIT 1",
                (session_key, cutoff),
            ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "name": row["name"]}

    # -- ratings -----------------------------------------------------------------
    def rate(self, session_key: str, contestant_id: int, stars: int) -> Optional[dict[str, Any]]:
        if not 1 <= stars <= 5:
            return None
        with self._lock:
            contestant = self._row("SELECT * FROM contestants WHERE id = ?", (contestant_id,))
            if contestant is None:
                return None
            existing = self._conn.execute(
                "SELECT stars FROM ratings WHERE session_key = ? AND contestant_id = ?",
                (session_key, contestant_id),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "UPDATE contestants SET rating_sum = rating_sum + ?, rating_count = rating_count + 1 "
                    "WHERE id = ?",
                    (stars, contestant_id),
                )
            else:
                self._conn.execute(
                    "UPDATE contestants SET rating_sum = rating_sum + ? WHERE id = ?",
                    (stars - existing["stars"], contestant_id),
                )
            self._conn.execute(
                "INSERT INTO ratings (session_key, contestant_id, stars, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_key, contestant_id) DO UPDATE SET stars = excluded.stars, "
                "updated_at = excluded.updated_at",
                (session_key, contestant_id, stars, _utcnow()),
            )
            self._conn.commit()
        return self.contestant(contestant_id)

    def rating_for(self, session_key: str, contestant_id: int) -> Optional[int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT stars FROM ratings WHERE session_key = ? AND contestant_id = ?",
                (session_key, contestant_id),
            ).fetchone()
        return row["stars"] if row else None

    def rated_by_session(self, session_key: str) -> dict[int, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT contestant_id, stars FROM ratings WHERE session_key = ?", (session_key,)
            ).fetchall()
        return {r["contestant_id"]: r["stars"] for r in rows}

    # -- news ---------------------------------------------------------------------
    def latest_news(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM news ORDER BY published_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_news(self, title: str, body: str, category: str, published_at: Optional[str] = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO news (title, body, category, published_at) VALUES (?, ?, ?, ?)",
                (title, body, category, published_at or _utcnow()),
            )
            self._conn.commit()

    # -- trivia ---------------------------------------------------------------------
    def next_trivia(self, session_key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            seen = {
                r["trivia_id"] for r in self._conn.execute(
                    "SELECT trivia_id FROM trivia_answers WHERE session_key = ?", (session_key,)
                ).fetchall()
            }
            rows = self._conn.execute("SELECT * FROM trivia").fetchall()
        if not rows:
            return None
        unseen = [r for r in rows if r["id"] not in seen]
        pool = unseen or rows
        row = random.choice(pool)
        return {
            "id": row["id"],
            "question": row["question"],
            "options": json.loads(row["options"]),
            "difficulty": row["difficulty"],
            "category": row["category"],
            "answer_idx": row["answer_idx"] if not unseen else None,  # reveal only on replays
            "fun_fact": "",
        }

    def trivia_by_id(self, trivia_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM trivia WHERE id = ?", (trivia_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "question": row["question"],
            "options": json.loads(row["options"]),
            "answer_idx": row["answer_idx"],
            "difficulty": row["difficulty"],
            "category": row["category"],
            "fun_fact": row["fun_fact"],
        }

    def record_trivia(self, session_key: str, trivia_id: int, correct: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO trivia_answers (session_key, trivia_id, correct, created_at) VALUES (?, ?, ?, ?)",
                (session_key, trivia_id, 1 if correct else 0, _utcnow()),
            )
            self._conn.commit()

    def trivia_score(self, session_key: str) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT correct FROM trivia_answers WHERE session_key = ?", (session_key,)
            ).fetchall()
        total = len(rows)
        correct = sum(r["correct"] for r in rows)
        return {"answered": total, "correct": correct, "accuracy_pct": round(correct / total * 100, 1) if total else 0.0}

    # -- stats / misc -----------------------------------------------------------------
    def total_votes(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COALESCE(SUM(votes), 0) AS v FROM contestants").fetchone()["v"]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n_contestants = self._conn.execute("SELECT COUNT(*) AS n FROM contestants").fetchone()["n"]
            n_news = self._conn.execute("SELECT COUNT(*) AS n FROM news").fetchone()["n"]
            n_trivia = self._conn.execute("SELECT COUNT(*) AS n FROM trivia").fetchone()["n"]
            n_votes = self._conn.execute("SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
            n_ratings = self._conn.execute("SELECT COUNT(*) AS n FROM ratings").fetchone()["n"]
        return {
            "contestants": n_contestants,
            "news_items": n_news,
            "trivia_questions": n_trivia,
            "live_votes": n_votes,
            "live_ratings": n_ratings,
            "total_vote_tally": self.total_votes(),
        }

    # -- internal -------------------------------------------------------------------
    def _row(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchone()

    def execute_many(self, statements: list[tuple[str, tuple]]) -> None:
        with self._lock:
            for sql, params in statements:
                self._conn.execute(sql, params)
            self._conn.commit()

    def is_seeded(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS n FROM contestants").fetchone()["n"] > 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
