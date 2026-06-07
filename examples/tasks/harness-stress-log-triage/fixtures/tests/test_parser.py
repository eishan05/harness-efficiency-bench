import unittest

from parser import parse_duration


class ParserTest(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(parse_duration("1h 30m"), 90)

    def test_seconds_are_rounded_down_to_minutes(self):
        self.assertEqual(parse_duration("90s"), 1)

    def test_combined_seconds(self):
        self.assertEqual(parse_duration("1h 90s"), 61)


if __name__ == "__main__":
    unittest.main()
