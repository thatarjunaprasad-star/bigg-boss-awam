"""AwamAgent — intent routing, grounded response synthesis, and personality.

The agent is the brain that runs on top of the AwamInfer engine. It classifies
each message into an intent, pulls live data (votes, ratings, news, trivia)
and composes a reply in the Awam voice: classy, a little theatrical, lightly
Hinglish. When a remote LLM is configured the engine sends this synthesis as
grounded fact alongside the conversation.
"""
from __future__ import annotations

import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from ..core.telemetry import TelemetryService
from ..data.db import Database, VoteResult


INTENT_KEYWORDS: dict[str, list[str]] = {
    "vote": ["vote", "voting", "vada", "ballot", "poll karna", "cast"],
    "leaderboard": ["leaderboard", "leading", "who is winning", "who's winning", "top ",
                    "rank", "standing", "jeet", "winner right now", "ladder"],
    "ratings": ["rating", "rate", "stars", "star", "favourite", "favorite",
                "best performer", "most loved", "highest rated"],
    "news": ["news", "khabar", "update", "latest", "kya chal", "gossip", "feed"],
    "trivia": ["trivia", "quiz", "question", "puzzle", "khelo", "game", "challenge"],
    "engine": ["engine", "gpu", "diagnostic", "performance", "kv cache", "tokens",
               "inference", "throughput", "latency", "benchmark", "amd", "rocm"],
    "greeting": ["hi", "hello", "namaste", "namaskar", "hey", "salaam", "yo ",
                 "good morning", "good evening", "good afternoon"],
    "help": ["help", "what can you do", "capabilities", "features", "menu",
             "kya kar sakte", "commands"],
    "thanks": ["thanks", "thank you", "shukriya", "dhanyavad", "great job", "nice work"],
    "score": ["my score", "score", "kitne sahi", "accuracy"],
}

_MENU_HINTS = [
    "You can ask me for the leaderboard, latest news, a trivia round, or say 'vote for <name>'.",
    "Try: 'who's leading?', 'latest news', 'trivia time', or 'how is the engine doing?'",
    "Say 'help' for the full menu, Awam style.",
]

_OPENERS = [
    "Namaste, fandom!",
    "Aadaab, Awam!",
    "The eye sees everything, and today it saw you.",
    "The oracle is listening.",
    "Lights, camera, Awam!",
]


def _time_ago(iso_ts: str) -> str:
    try:
        ts = datetime.fromisoformat(iso_ts)
        delta = (datetime.now(timezone.utc) - ts).total_seconds()
    except ValueError:
        return "recently"
    if delta < 3600:
        return f"{max(int(delta // 60), 1)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


class _AgentSession:
    __slots__ = ("active_trivia_id", "trivia_started_at", "last_intent", "news_offset")

    def __init__(self) -> None:
        self.active_trivia_id: Optional[int] = None
        self.trivia_started_at: float = 0.0
        self.last_intent: str = ""
        self.news_offset: int = 0


class AwamAgent:
    def __init__(self, db: Database, engine, telemetry: TelemetryService,
                 vote_cooldown_hours: int = 24) -> None:
        self.db = db
        self.engine = engine
        self.telemetry = telemetry
        self.vote_cooldown_hours = vote_cooldown_hours
        self._sessions: dict[str, _AgentSession] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def respond(self, session_id: str, message: str) -> tuple[str, str]:
        """Returns (reply, intent)."""
        state = self._state(session_id)
        text = message.strip()
        lowered = text.lower()

        intent = self._classify(state, lowered, text)
        state.last_intent = intent

        handler = getattr(self, f"_on_{intent}", self._on_smalltalk)
        reply = handler(session_id, state, text, lowered)
        return reply, intent

    def live_context(self) -> str:
        """Grounded snapshot for the remote-LLM system prompt."""
        contestants = self.db.contestants()
        top5 = contestants[:5]
        rated = sorted(contestants, key=lambda c: c["rating_avg"], reverse=True)[:3]
        news = self.db.latest_news(3)
        lines = [
            "Bigg Boss Awam — unofficial fan poll. Live standings (vote tally):",
            *[f"  #{c['rank']} {c['name']} — {c['votes']:,} votes ({c['vote_share_pct']}%), rating {c['rating_avg']}/5"
              for c in top5],
            "Highest rated: " + "; ".join(f"{c['name']} ({c['rating_avg']}/5)" for c in rated),
            "Latest fan-feed headlines: " + "; ".join(n["title"] for n in news),
            "Answer in the Awam voice: warm, classy, lightly Hinglish, never mean.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------- classification
    def _classify(self, state: _AgentSession, lowered: str, original: str) -> str:
        if state.active_trivia_id is not None and re.fullmatch(
            r"(?:option\s*)?[a-d1-4][).:]?", lowered.strip()
        ):
            return "trivia_answer"

        if re.fullmatch(r"(more|next|aur|phir|another|again)[.!]?", lowered.strip()):
            if state.last_intent in ("news", "trivia", "leaderboard"):
                return state.last_intent

        scores: dict[str, int] = {}
        for intent, keywords in INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in lowered)
            if score:
                scores[intent] = score
        if scores:
            return max(scores, key=lambda k: (scores[k], k))

        contestant = self.db.find_contestant(original)
        if contestant is not None:
            return "contestant_info"

        if "vote" in lowered or "vada" in lowered:
            return "vote"
        return "smalltalk"

    # ----------------------------------------------------------------- handlers
    def _on_greeting(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        leader = self.db.contestants()[0]
        return (
            f"{random.choice(_OPENERS)} I'm **Awam** — the people's oracle for all things Bigg Boss "
            f"(strictly unofficial, endlessly opinionated).\n\n"
            f"Right now **{leader['name']}** sits on top of the ladder with {leader['votes']:,} votes. "
            f"{random.choice(_MENU_HINTS)}"
        )

    def _on_help(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        return (
            "Here's what the Awam can do for you:\n"
            "• **Leaderboard** — 'who's leading?' and I'll read out the ladder\n"
            "• **Vote** — 'vote for Shehnaaz Gill' (one vote per 24 hours, play fair)\n"
            "• **Ratings** — 'who's the highest rated legend?'\n"
            "• **News** — 'latest khabar' from the fan feed\n"
            "• **Trivia** — 'trivia time' starts a round; reply A/B/C/D to answer\n"
            "• **Contestants** — name any legend for their profile card\n"
            "• **Engine Room** — 'how's the engine?' for KV-cache and throughput gossip\n\n"
            "The Engine Room tab on the site has the live diagnostics dashboard."
        )

    def _on_leaderboard(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        contestants = self.db.contestants()
        rows = []
        medals = {1: "👑", 2: "🥈", 3: "🥉"}
        for c in contestants[:5]:
            badge = medals.get(c["rank"], f"#{c['rank']}")
            rows.append(f"{badge} **{c['name']}** — {c['votes']:,} votes · {c['vote_share_pct']}% share · ⭐ {c['rating_avg']}")
        tail = contestants[5]["name"] if len(contestants) > 5 else ""
        return (
            "The Awam ladder, live and merciless:\n\n" + "\n".join(rows) +
            (f"\n\nNeck-and-neck with {tail} right behind — every vote rewrites this. "
             if tail else "") +
            f"\n\nTotal tally: {self.db.total_votes():,} votes cast."
        )

    def _on_ratings(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        contestants = sorted(self.db.contestants(), key=lambda c: c["rating_avg"], reverse=True)
        rows = [
            f"{'⭐' * round(c['rating_avg'])} **{c['name']}** — {c['rating_avg']}/5 "
            f"from {c['rating_count']} Awam ratings"
            for c in contestants[:5]
        ]
        return (
            "The Awam Ratings Board — where the fandom judges in stars:\n\n" + "\n".join(rows) +
            "\n\nAdd your own stars from the Ratings tab; the board is watching."
        )

    def _on_vote(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        match = re.search(r"(?:vote(?:\s+for)?|vada(?:\s+for)?)\s+(?:for\s+)?(.+)", lowered)
        query = match.group(1).strip(" .!?") if match else ""
        # strip filler words people add
        for filler in ("please", "plz", "pls", "jaldi", "kar do", "kardo", "now", "today"):
            query = re.sub(rf"\b{filler}\b", "", query).strip()
        query = re.sub(r"[^a-z\s'-]", "", query).strip()

        contestant = self.db.find_contestant(query) if query else None
        if contestant is None:
            names = ", ".join(c["name"] for c in self.db.contestants()[:6])
            return (
                "Tell me who gets your vote, Awam — say something like *'vote for Karan Veer Mehra'*.\n"
                f"Currently in the spotlight: {names}… and the rest of the legends on the Vote tab.\n"
                f"One vote per 24 hours, so choose like a jury member."
            )

        result = self.db.cast_vote(session_id, contestant["id"], self.vote_cooldown_hours)
        if result.status == VoteResult.CAST:
            self.telemetry.bump("votes")
            c = result.contestant
            return (
                f"🗳️ **Vote recorded!** {c['name']} climbs to #{c['rank']} with {c['votes']:,} votes "
                f"({c['vote_share_pct']}% share).\n"
                f"The {self.vote_cooldown_hours}-hour lock is on — the Awam votes once, and votes well."
            )
        if result.status == VoteResult.COOLDOWN:
            return (
                f"Arre, patience! You've already voted in the last {self.vote_cooldown_hours} hours "
                f"({result.detail}). Come back tomorrow and the oracle shall listen again."
            )
        return "Hmm, I couldn't find that legend on the ladder. Check the Vote tab for the full roster."

    def _on_news(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        all_news = self.db.latest_news(20)
        if not all_news:
            return "The feed is quiet tonight — even the confession room is asleep."
        chunk = all_news[state.news_offset: state.news_offset + 3]
        if not chunk:
            state.news_offset = 0
            chunk = all_news[:3]
        state.news_offset += 3
        items = [f"**[{n['category']}]** {n['title']} — _{_time_ago(n['published_at'])}_" for n in chunk]
        more = "\n\nSay *'more'* for the next round of khabar." if state.news_offset < len(all_news) else ""
        return "From the Awam Fan Feed (unofficial, obviously):\n\n" + "\n".join(items) + more

    def _on_trivia(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        return self._serve_trivia(session_id, state)

    def _serve_trivia(self, session_id: str, state: _AgentSession) -> str:
        question = self.db.next_trivia(session_id)
        if question is None:
            return "The trivia vault is empty — even I'm impressed."
        state.active_trivia_id = question["id"]
        state.trivia_started_at = time.time()
        options = "\n".join(
            f"{'ABCD'[i]}) {opt}" for i, opt in enumerate(question["options"])
        )
        return (
            f"🎙️ **Awam Trivia — {question['category']}** ({question['difficulty']})\n\n"
            f"{question['question']}\n\n{options}\n\n"
            "Reply with A, B, C or D. No lifelines, no Googling — the eye is watching."
        )

    def _on_trivia_answer(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        if state.active_trivia_id is None:
            return self._serve_trivia(session_id, state)
        answer = lowered.strip()[0].lower()
        idx = "abcd".find(answer) if answer in "abcd" else (int(answer) - 1 if answer.isdigit() else -1)
        question = self.db.trivia_by_id(state.active_trivia_id)
        if question is None or idx < 0 or idx >= len(question["options"]):
            return "That's not on the card — reply A, B, C or D. The eye forgives typos, not silence."
        correct_idx = question["answer_idx"]
        is_correct = idx == correct_idx
        self.db.record_trivia(session_id, question["id"], is_correct)
        self.telemetry.bump("trivia_answers")
        if is_correct:
            self.telemetry.bump("trivia_correct")
        state.active_trivia_id = None
        score = self.db.trivia_score(session_id)
        verdict = (
            random.choice(["Ekdum correct!", "Bullseye, Awam!", "Sahi jawaab!"]) if is_correct
            else random.choice(["Close, but the eye says no.", "Nahi hota, dost — wrong answer.",
                                "The oracle winces. Incorrect."])
        )
        correct_line = "" if is_correct else f"\n\nThe answer was **{'ABCD'[correct_idx]}) {question['options'][correct_idx]}**."
        fact = f"\n\n_💡 {question['fun_fact']}_" if question.get("fun_fact") else ""
        return (
            f"{'✅' if is_correct else '❌'} {verdict}{correct_line}{fact}\n\n"
            f"Your record: **{score['correct']}/{score['answered']}** "
            f"({score['accuracy_pct']}% accuracy). Say *'trivia'* for the next one."
        )

    def _on_score(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        score = self.db.trivia_score(session_id)
        if score["answered"] == 0:
            return "Your scoreboard is a blank page, Awam. Say *'trivia'* and let's fix that."
        return (
            f"Your trivia record: **{score['correct']}/{score['answered']} correct** "
            f"({score['accuracy_pct']}% accuracy). "
            + ("Bigg Boss himself would hire you as a fact-checker." if score["accuracy_pct"] >= 70
               else "The eye believes in improvement arcs. Say 'trivia' for another round.")
        )

    def _on_contestant_info(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        contestant = self.db.find_contestant(text)
        if contestant is None:
            return self._on_smalltalk(session_id, state, text, lowered)
        stars = "⭐" * round(contestant["rating_avg"])
        return (
            f"**{contestant['name']}** — *{contestant['tagline']}*\n"
            f"🏛️ {contestant['season']} · {contestant['profession']} · {contestant['house_status']}\n\n"
            f"📊 Ladder position: **#{contestant['rank']}** with {contestant['votes']:,} votes "
            f"({contestant['vote_share_pct']}% share)\n"
            f"{stars or '—'} Awam rating: **{contestant['rating_avg']}/5** "
            f"({contestant['rating_count']} ratings)\n\n"
            + (f"Want to back them? Say *'vote for {contestant['name'].split()[0]}'*."
               if self.db.vote_today(session_id, self.vote_cooldown_hours) is None
               else "Your daily vote is already spent — the oracle keeps receipts.")
        )

    def _on_engine(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        info = self.engine.engine_info()
        device = self.engine.device_info
        kv = self.engine.kv_cache.stats()
        overview = self.telemetry.overview()
        return (
            f"🛠️ **Engine Room report — AwamInfer {info['version']}**\n\n"
            f"🖥️ Device: **{device.label}**"
            + (f" (ROCm {device.rocm_version})" if device.rocm_version else "") + "\n"
            f"⚙️ Tuning profile: **{self.engine.tuner.active_profile.label}** — "
            f"{self.engine.tuner.active_profile.description}\n"
            f"🗄️ KV cache: **{kv.utilization_pct}%** utilised ({kv.used_blocks}/{kv.capacity_blocks} blocks), "
            f"hit rate **{kv.hit_rate_pct}%**, {kv.evicted_sessions} session evictions\n"
            f"⚡ Throughput: **{overview['tokens_per_sec']} tokens/sec** · "
            f"latency p50 {overview['latency_recent']['p50']}ms / p95 {overview['latency_recent']['p95']}ms\n"
            f"🧮 Served {overview['requests']} requests, {overview['tokens_out']:,} tokens out\n\n"
            + ("A ROCm build of PyTorch will light up the AMD GPU path with flash attention."
               if not device.accelerator_available else
               "The GPU is warm and the kernels are golden.")
        )

    def _on_thanks(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        return random.choice([
            "Anytime, Awam. The oracle works for applause and chai.",
            "Shukriya right back at you. Now go vote — the ladder awaits.",
            "Pleasure's mine. The eye appreciates good manners.",
        ])

    def _on_smalltalk(self, session_id: str, state: _AgentSession, text: str, lowered: str) -> str:
        return random.choice([
            "Interesting… the confession room has heard stranger, but not by much. "
            "Ask me about the leaderboard, news, trivia — or type 'help' for the full menu.",
            "The eye blinks twice at that one. I do votes, ratings, news, trivia and engine gossip — "
            "say 'help' and I'll show off.",
            "Hmm, that's between you and the Bigg Boss eye. Meanwhile: leaderboard? Trivia? Latest khabar?",
        ])

    # ---------------------------------------------------------------- internal
    def _state(self, session_id: str) -> _AgentSession:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                state = _AgentSession()
                self._sessions[session_id] = state
            return state
