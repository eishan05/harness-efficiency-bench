import unittest

from harness_efficiency_bench.metrics import compute_run_metrics
from harness_efficiency_bench.tokenization import count_tokens
from harness_efficiency_bench.tracing import model_call_event, tool_result_event


class MetricsTest(unittest.TestCase):
    def test_metrics_from_full_trace(self):
        prompt = "fix the bug"
        tool_output = "test log failed at line 10"
        events = [
            model_call_event(call_index=0, input_text="system prompt fix the bug", input_tokens=5, output_tokens=1),
            tool_result_event(name="pytest", output=tool_output),
            model_call_event(
                call_index=1,
                input_text=f"system prompt fix the bug old output {tool_output}",
                input_tokens=12,
                output_tokens=1,
            ),
        ]
        metrics = compute_run_metrics(events, count_tokens(prompt))
        self.assertEqual(metrics["startup_tax"]["status"], "full")
        self.assertEqual(metrics["startup_tax"]["value"], 2)
        self.assertEqual(metrics["context_growth_rate"]["status"], "full")
        self.assertGreater(metrics["context_growth_rate"]["value"], 0)
        self.assertEqual(metrics["tool_output_retention_ratio"]["status"], "full")
        self.assertGreater(metrics["tool_output_retention_ratio"]["value"], 0)


if __name__ == "__main__":
    unittest.main()

