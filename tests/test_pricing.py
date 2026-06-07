import unittest

from harness_efficiency_bench.pricing import estimate_call_cost


class PricingTest(unittest.TestCase):
    def test_estimates_uncached_cached_and_output_cost(self):
        cost = estimate_call_cost(
            {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100},
            {
                "input_per_million": 2.5,
                "cached_input_per_million": 0.25,
                "output_per_million": 15.0,
            },
        )
        self.assertAlmostEqual(cost, 0.00355)


if __name__ == "__main__":
    unittest.main()

