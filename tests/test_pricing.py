import unittest

from harness_efficiency_bench.manifests import HarnessManifest
from harness_efficiency_bench.pricing import apply_pricing, estimate_call_cost
from harness_efficiency_bench.tracing import model_call_event


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

    def test_reasoning_tokens_are_not_double_counted_by_default(self):
        cost = estimate_call_cost(
            {"input_tokens": 0, "output_tokens": 100, "reasoning_output_tokens": 40},
            {"output_per_million": 30.0},
        )
        self.assertAlmostEqual(cost, 0.003)

    def test_long_context_pricing(self):
        cost = estimate_call_cost(
            {"input_tokens": 300_000, "cached_input_tokens": 100_000, "output_tokens": 1_000},
            {
                "input_per_million": 5.0,
                "cached_input_per_million": 0.5,
                "output_per_million": 30.0,
                "long_context_threshold_tokens": 272_000,
                "long_context_input_per_million": 10.0,
                "long_context_cached_input_per_million": 1.0,
                "long_context_output_per_million": 45.0,
            },
        )
        self.assertAlmostEqual(cost, 2.145)

    def test_apply_pricing_uses_long_context_for_whole_run(self):
        harness = HarnessManifest(
            id="priced",
            adapter="demo",
            path=__file__,
            pricing={
                "input_per_million": 1.0,
                "output_per_million": 1.0,
                "long_context_threshold_tokens": 10,
                "long_context_input_per_million": 2.0,
                "long_context_output_per_million": 3.0,
            },
        )
        events = [
            model_call_event(call_index=0, input_tokens=5, output_tokens=1),
            model_call_event(call_index=1, input_tokens=11, output_tokens=1),
        ]
        apply_pricing(events, harness)
        self.assertAlmostEqual(events[0].data["cost_usd"], 0.000013)
        self.assertEqual(events[0].data["metadata"]["pricing_context"], "long")


if __name__ == "__main__":
    unittest.main()
