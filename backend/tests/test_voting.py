import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.data.db import Database, VoteResult  # noqa: E402
from app.data.seed import seed  # noqa: E402


def _fresh_db() -> tuple[Database, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory(prefix="awam_test_")
    db = Database(Path(tmp.name) / "awam.db")
    seed(db)
    return db, tmp


class TestVotingRules(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _fresh_db()
        self.first_id = self.db.contestants()[0]["id"]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_first_vote_cast(self):
        result = self.db.cast_vote("s1", self.first_id)
        self.assertEqual(result.status, VoteResult.CAST)
        self.assertEqual(result.contestant["id"], self.first_id)
        self.assertIsNotNone(self.db.vote_today("s1"))

    def test_cooldown_blocks_second_vote_same_day(self):
        self.assertEqual(self.db.cast_vote("s1", self.first_id).status, VoteResult.CAST)
        second = self.db.cast_vote("s1", self.first_id)
        self.assertEqual(second.status, VoteResult.COOLDOWN)

    def test_cooldown_blocks_vote_for_different_contestant(self):
        other_id = self.db.contestants()[1]["id"]
        self.assertEqual(self.db.cast_vote("s1", self.first_id).status, VoteResult.CAST)
        self.assertEqual(self.db.cast_vote("s1", other_id).status, VoteResult.COOLDOWN)

    def test_cooldown_is_per_session(self):
        self.assertEqual(self.db.cast_vote("s1", self.first_id).status, VoteResult.CAST)
        self.assertEqual(self.db.cast_vote("s2", self.first_id).status, VoteResult.CAST)

    def test_vote_increments_tally_once(self):
        before = self.db.total_votes()
        self.db.cast_vote("s1", self.first_id)
        self.assertEqual(self.db.total_votes(), before + 1)
        self.db.cast_vote("s1", self.first_id)  # cooldown — must not double count
        self.assertEqual(self.db.total_votes(), before + 1)

    def test_unknown_contestant(self):
        result = self.db.cast_vote("s1", 99999)
        self.assertEqual(result.status, VoteResult.UNKNOWN)

    def test_expired_cooldown_allows_new_vote(self):
        # Backdate the recorded vote beyond the window.
        self.db.cast_vote("s1", self.first_id)
        self.db.execute_many([
            ("UPDATE votes SET created_at = '2000-01-01T00:00:00+00:00'", ()),
        ])
        self.assertIsNone(self.db.vote_today("s1"))
        self.assertEqual(self.db.cast_vote("s1", self.first_id).status, VoteResult.CAST)


class TestRatings(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _fresh_db()
        self.cid = self.db.contestants()[0]["id"]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_new_rating_adds_count(self):
        before = self.db.contestant(self.cid)
        self.db.rate("s1", self.cid, 5)
        after = self.db.contestant(self.cid)
        self.assertEqual(after["rating_count"], before["rating_count"] + 1)
        self.assertEqual(self.db.rating_for("s1", self.cid), 5)

    def test_rating_edit_adjusts_sum_not_count(self):
        self.db.rate("s1", self.cid, 2)
        before = self.db.contestant(self.cid)
        self.db.rate("s1", self.cid, 4)  # edit: +2 to the sum, count unchanged
        after = self.db.contestant(self.cid)
        self.assertEqual(after["rating_count"], before["rating_count"])
        # average rises by exactly (4 - 2) / count
        self.assertAlmostEqual(after["rating_avg"],
                               before["rating_avg"] + 2.0 / before["rating_count"], delta=0.02)
        self.assertEqual(self.db.rating_for("s1", self.cid), 4)

    def test_star_bounds_enforced(self):
        before = self.db.contestant(self.cid)
        self.assertIsNone(self.db.rate("s1", self.cid, 0))
        self.assertIsNone(self.db.rate("s1", self.cid, 6))
        self.assertIsNone(self.db.rate("s1", self.cid, -3))
        after = self.db.contestant(self.cid)
        self.assertEqual(after["rating_count"], before["rating_count"])
        self.assertEqual(after["rating_avg"], before["rating_avg"])

    def test_ratings_are_per_session(self):
        self.db.rate("s1", self.cid, 5)
        self.db.rate("s2", self.cid, 1)
        self.assertEqual(self.db.rating_for("s1", self.cid), 5)
        self.assertEqual(self.db.rating_for("s2", self.cid), 1)
        self.assertEqual(len(self.db.rated_by_session("s1")), 1)
        self.assertEqual(len(self.db.rated_by_session("s3")), 0)


class TestContestantLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _fresh_db()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_exact_full_name(self):
        self.assertEqual(self.db.find_contestant("Sidharth Shukla")["name"], "Sidharth Shukla")

    def test_first_name(self):
        self.assertEqual(self.db.find_contestant("shehnaaz")["name"], "Shehnaaz Gill")

    def test_case_insensitive(self):
        self.assertEqual(self.db.find_contestant("MC STAN")["name"], "MC Stan")

    def test_fuzzy_typo(self):
        self.assertIsNotNone(self.db.find_contestant("Sidhart Shukla"))

    def test_no_match(self):
        self.assertIsNone(self.db.find_contestant("random person"))
        self.assertIsNone(self.db.find_contestant(""))


class TestSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self._tmp = _fresh_db()

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_deterministic_seed(self):
        db2, tmp2 = _fresh_db()
        try:
            a = [(c["name"], c["votes"]) for c in self.db.contestants()]
            b = [(c["name"], c["votes"]) for c in db2.contestants()]
            self.assertEqual(a, b)
        finally:
            db2.close()
            tmp2.cleanup()

    def test_seed_is_idempotent(self):
        seed(self.db)  # second call must be a no-op
        self.assertEqual(len(self.db.contestants()), 12)
        self.assertEqual(len(self.db.latest_news(50)), 10)

    def test_vote_share_sums_to_100(self):
        share = sum(c["vote_share_pct"] for c in self.db.contestants())
        self.assertAlmostEqual(share, 100.0, delta=1.0)

    def test_settings_defaults(self):
        s = Settings()
        self.assertEqual(s.kv_num_blocks, 4096)
        self.assertEqual(s.kv_block_size, 16)
        self.assertEqual(s.default_profile, "balanced")


if __name__ == "__main__":
    unittest.main()
