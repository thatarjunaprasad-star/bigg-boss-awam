import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.inference.kv_cache import PagedKVCacheManager  # noqa: E402


class TestPagedKVCache(unittest.TestCase):
    def test_first_append_is_all_miss(self):
        kv = PagedKVCacheManager(num_blocks=64, block_size=4, max_session_tokens=32)
        result = kv.append("s1", list(range(10)))
        self.assertEqual(result.cached_prefix_tokens, 0)
        self.assertEqual(result.appended_tokens, 10)
        self.assertEqual(result.resident_tokens, 10)
        stats = kv.stats()
        self.assertEqual(stats.hits, 0)
        self.assertEqual(stats.misses, 10)
        self.assertEqual(stats.used_blocks, 3)  # ceil(10/4)

    def test_second_append_hits_prefix(self):
        kv = PagedKVCacheManager(num_blocks=64, block_size=4, max_session_tokens=32)
        kv.append("s1", list(range(10)))
        result = kv.append("s1", list(range(10, 15)))
        self.assertEqual(result.cached_prefix_tokens, 10)
        self.assertEqual(result.appended_tokens, 5)
        self.assertEqual(result.resident_tokens, 15)
        self.assertEqual(kv.stats().hit_rate_pct, 40.0)  # 10 hits / 25 total lookups

    def test_sliding_window_drops_oldest(self):
        kv = PagedKVCacheManager(num_blocks=64, block_size=4, max_session_tokens=8)
        kv.append("s1", [1, 2, 3, 4, 5, 6, 7, 8])
        result = kv.append("s1", [9, 10, 11, 12])
        self.assertEqual(result.resident_tokens, 8)          # capped at window
        self.assertEqual(result.cached_prefix_tokens, 8)     # full prefix was cached
        self.assertGreaterEqual(result.slid_blocks, 1)
        # the resident view reflects the slid window
        self.assertEqual(kv.resident("s1"), 8)
        self.assertGreaterEqual(kv.stats().slid_blocks, 1)  # aggregate counter

    def test_lru_eviction_under_pool_pressure(self):
        kv = PagedKVCacheManager(num_blocks=4, block_size=4, max_session_tokens=64)
        kv.append("old", [1] * 8)      # 2 blocks
        kv.append("mid", [2] * 8)      # 2 blocks — pool full
        evicted = kv.append("new", [3] * 8)  # needs 2 more blocks → evict LRU ("old")
        self.assertIn("old", evicted.evicted_sessions)
        self.assertEqual(kv.resident("old"), 0)
        self.assertGreaterEqual(kv.stats().evicted_sessions, 1)

    def test_stats_snapshot(self):
        kv = PagedKVCacheManager(num_blocks=16, block_size=4, max_session_tokens=16)
        kv.append("a", [1] * 8)
        kv.append("a", [2] * 8)
        stats = kv.stats()
        self.assertEqual(stats.active_sessions, 1)
        self.assertEqual(stats.tokens_cached, 16)
        self.assertEqual(stats.used_blocks, 4)
        self.assertEqual(stats.capacity_blocks, 16)
        self.assertEqual(stats.utilization_pct, 25.0)

    def test_drop_session(self):
        kv = PagedKVCacheManager()
        kv.append("s1", [1, 2, 3])
        kv.drop_session("s1")
        self.assertEqual(kv.resident("s1"), 0)
        self.assertEqual(kv.stats().active_sessions, 0)

    def test_thread_safety_smoke(self):
        import threading

        kv = PagedKVCacheManager(num_blocks=1024, block_size=4, max_session_tokens=64)
        errors = []

        def worker(n: int) -> None:
            try:
                for i in range(200):
                    kv.append(f"s{n}", [i % 1000] * 6)
                    kv.stats()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(kv.stats().active_sessions, 8)


if __name__ == "__main__":
    unittest.main()
