import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.awam import AwamAgent  # noqa: E402
from app.core.telemetry import TelemetryService  # noqa: E402
from app.data.db import Database, VoteResult  # noqa: E402
from app.data.seed import seed  # noqa: E402
from app.inference.kv_cache import PagedKVCacheManager  # noqa: E402


@dataclass
class _FakeDevice:
    label: str = "Test CPU"
    rocm_version: str = ""
    accelerator_available: bool = False


class _FakeProfile:
    label = "Balanced"
    description = "test profile"


class _FakeTuner:
    active_profile = _FakeProfile()


class _FakeEngine:
    device_info = _FakeDevice()
    tuner = _FakeTuner()
    kv_cache = PagedKVCacheManager()

    def engine_info(self) -> dict:
        return {"version": "test", "engine": "awam-local"}


class TestIntentClassification(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="awam_agent_")
        self._tmp = tmp
        self.db = Database(Path(tmp.name) / "awam.db")
        seed(self.db)
        self.agent = AwamAgent(self.db, _FakeEngine(), TelemetryService())

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def _intent(self, message: str, session: str = "t1") -> str:
        _, intent = self.agent.respond(session, message)
        return intent

    def test_greeting(self):
        self.assertEqual(self._intent("hello"), "greeting")
        self.assertEqual(self._intent("namaste"), "greeting")

    def test_leaderboard(self):
        self.assertEqual(self._intent("who is winning?"), "leaderboard")
        self.assertEqual(self._intent("show me the leaderboard"), "leaderboard")

    def test_news(self):
        self.assertEqual(self._intent("latest news please"), "news")
        self.assertEqual(self._intent("kya chal raha hai?"), "news")

    def test_engine(self):
        self.assertEqual(self._intent("how is the KV cache doing?"), "engine")
        self.assertEqual(self._intent("amd gpu diagnostics"), "engine")

    def test_help_and_thanks(self):
        self.assertEqual(self._intent("help"), "help")
        self.assertEqual(self._intent("thank you!"), "thanks")

    def test_contestant_name_routes_to_info(self):
        self.assertEqual(self._intent("Tell me about Shehnaaz Gill"), "contestant_info")
        self.assertEqual(self._intent("sidharth shukla"), "contestant_info")

    def test_unknown_falls_to_smalltalk(self):
        self.assertEqual(self._intent("the weather on Mars"), "smalltalk")


class TestAgentHandlers(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="awam_agent_")
        self._tmp = tmp
        self.db = Database(Path(tmp.name) / "awam.db")
        seed(self.db)
        self.telemetry = TelemetryService()
        self.agent = AwamAgent(self.db, _FakeEngine(), self.telemetry)
        self.sid = "sess-1"

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_vote_flow_cast_then_cooldown(self):
        reply, intent = self.agent.respond(self.sid, "vote for Shehnaaz Gill")
        self.assertEqual(intent, "vote")
        self.assertIn("Vote recorded", reply)
        self.assertEqual(self.telemetry.counters.votes, 1)

        reply, _ = self.agent.respond(self.sid, "vote for MC Stan")
        self.assertIn("patience", reply)  # cooldown message

    def test_vote_without_name_prompts_roster(self):
        reply, intent = self.agent.respond(self.sid, "I want to vote")
        self.assertEqual(intent, "vote")
        self.assertIn("vote for", reply)

    def test_leaderboard_mentions_top_contestant(self):
        reply, _ = self.agent.respond(self.sid, "who is winning?")
        top = self.db.contestants()[0]
        self.assertIn(top["name"], reply)

    def test_trivia_round_trip_correct_answer(self):
        reply, intent = self.agent.respond(self.sid, "trivia time")
        self.assertEqual(intent, "trivia")
        self.assertIn("A", reply)

        active = self.agent._sessions[self.sid].active_trivia_id
        question = self.db.trivia_by_id(active)
        correct_letter = "ABCD"[question["answer_idx"]]

        reply, intent = self.agent.respond(self.sid, correct_letter)
        self.assertEqual(intent, "trivia_answer")
        self.assertIn("✅", reply)
        self.assertIn("1/1", reply)

    def test_trivia_wrong_answer_reveals_solution(self):
        self.agent.respond(self.sid, "trivia")
        active = self.agent._sessions[self.sid].active_trivia_id
        question = self.db.trivia_by_id(active)
        wrong_letter = "ABCD"[(question["answer_idx"] + 1) % len(question["options"])]

        reply, _ = self.agent.respond(self.sid, wrong_letter)
        self.assertIn("❌", reply)
        self.assertIn("The answer was", reply)
        score = self.db.trivia_score(self.sid)
        self.assertEqual(score["answered"], 1)
        self.assertEqual(score["correct"], 0)

    def test_news_pagination_with_more(self):
        _, intent = self.agent.respond(self.sid, "latest khabar")
        self.assertEqual(intent, "news")
        reply, intent = self.agent.respond(self.sid, "more")
        self.assertEqual(intent, "news")  # continuation
        self.assertIn("From the Awam Fan Feed", reply)

    def test_score_intent_reports_record(self):
        reply, intent = self.agent.respond(self.sid, "what is my score")
        self.assertEqual(intent, "score")
        self.assertIn("blank page", reply)

    def test_contestant_info_card(self):
        reply, _ = self.agent.respond(self.sid, "Gauahar Khan")
        self.assertIn("Gauahar Khan", reply)
        self.assertIn("#", reply)

    def test_engine_report_includes_kv_stats(self):
        reply, _ = self.agent.respond(self.sid, "engine diagnostics")
        self.assertIn("Engine Room report", reply)
        self.assertIn("KV cache", reply)

    def test_sessions_are_isolated(self):
        self.agent.respond("alice", "vote for MC Stan")
        reply, _ = self.agent.respond("bob", "vote for MC Stan")
        self.assertIn("Vote recorded", reply)  # bob is not blocked by alice's vote


if __name__ == "__main__":
    unittest.main()
