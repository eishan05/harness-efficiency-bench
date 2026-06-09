import unittest

from windowing import bucket_start


class WindowingTest(unittest.TestCase):
    def test_buckets_utc_timestamp(self):
        self.assertEqual(bucket_start("2026-06-09T10:07:30Z", 15), "2026-06-09T10:00:00Z")

    def test_converts_offset_to_utc_before_bucket(self):
        self.assertEqual(bucket_start("2026-06-09T23:58:00-04:00", 30), "2026-06-10T03:30:00Z")

    def test_handles_previous_day_after_utc_conversion(self):
        self.assertEqual(bucket_start("2026-06-09T00:02:00+02:00", 15), "2026-06-08T22:00:00Z")


if __name__ == "__main__":
    unittest.main()
