import unittest

from ttl_cache import TTLCache


class TTLCacheTest(unittest.TestCase):
    def test_expired_entry_is_removed_on_access(self):
        clock = [100.0]
        cache = TTLCache(capacity=2, ttl_seconds=10, now=lambda: clock[0])

        cache.set("a", "A")
        clock[0] = 111.0

        self.assertIsNone(cache.get("a"))
        self.assertEqual(len(cache), 0)

    def test_get_updates_lru_recency(self):
        clock = [100.0]
        cache = TTLCache(capacity=2, ttl_seconds=30, now=lambda: clock[0])

        cache.set("a", "A")
        cache.set("b", "B")
        self.assertEqual(cache.get("a"), "A")
        cache.set("c", "C")

        self.assertEqual(cache.get("a"), "A")
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("c"), "C")


if __name__ == "__main__":
    unittest.main()
