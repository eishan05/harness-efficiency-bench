import unittest

from harness_efficiency_bench.metrics import compute_run_metrics, research_metric_coverage
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

    def test_aggregate_only_usage_marks_startup_tax_partial(self):
        prompt = "fix the bug"
        events = [
            model_call_event(
                call_index=0,
                input_tokens=100,
                output_tokens=5,
                metadata={"source": "claude_openrouter_model_usage", "aggregate": True},
            )
        ]

        metrics = compute_run_metrics(events, count_tokens(prompt))

        self.assertEqual(metrics["startup_tax"]["status"], "partial")
        self.assertEqual(metrics["startup_tax"]["value"], 97)
        self.assertIn("aggregate run usage", metrics["startup_tax"]["details"]["reason"])
        self.assertEqual(metrics["context_growth_rate"]["status"], "unsupported")
        self.assertIn("non-aggregate", metrics["context_growth_rate"]["details"]["reason"])

    def test_context_growth_ignores_aggregate_usage_points(self):
        events = [
            model_call_event(call_index=0, input_tokens=10, output_tokens=1),
            model_call_event(
                call_index=1,
                input_tokens=100,
                output_tokens=5,
                metadata={"source": "aggregate_usage", "aggregate": True},
            ),
            model_call_event(call_index=2, input_tokens=20, output_tokens=1),
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        self.assertEqual(metrics["context_growth_rate"]["status"], "full")
        self.assertEqual(metrics["context_growth_rate"]["details"]["points"], [(0.0, 10.0), (2.0, 20.0)])
        self.assertEqual(metrics["context_growth_rate"]["value"], 5.0)

    def test_startup_tax_sums_provider_first_and_task_first_when_distinct(self):
        prompt = "fix the bug"
        events = [
            model_call_event(
                call_index=0,
                input_tokens=50,
                output_tokens=1,
                metadata={"source": "usage_proxy", "preflight": True},
            ),
            model_call_event(call_index=1, input_tokens=100, output_tokens=2),
            model_call_event(call_index=2, input_tokens=120, output_tokens=2),
        ]

        metrics = compute_run_metrics(events, count_tokens(prompt))

        self.assertEqual(metrics["startup_tax"]["status"], "full")
        self.assertEqual(metrics["startup_tax"]["value"], 144)
        self.assertEqual(metrics["startup_tax"]["details"]["provider_first_startup_tax"], 47)
        self.assertEqual(metrics["startup_tax"]["details"]["task_first_startup_tax"], 97)
        self.assertEqual(
            metrics["startup_tax"]["details"]["composition"],
            "provider_first_startup_tax + task_first_startup_tax",
        )
        self.assertEqual(metrics["context_growth_rate"]["status"], "full")
        self.assertEqual(metrics["context_growth_rate"]["details"]["points"], [(1.0, 100.0), (2.0, 120.0)])
        self.assertEqual(metrics["usage"]["input_tokens"], 270)

    def test_research_coverage_tracks_research_metrics_only(self):
        coverage = research_metric_coverage(
            [
                {
                    "metrics": {
                        "startup_tax": {"status": "full"},
                        "context_growth_rate": {"status": "full"},
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "reasoning_output_tokens": 0,
                        },
                    }
                }
            ]
        )

        self.assertEqual(set(coverage), {"startup_tax", "context_growth_rate", "solve_efficiency"})
        self.assertEqual(coverage["solve_efficiency"]["status"], "full")
        self.assertEqual(coverage["solve_efficiency"]["runs_with_token_cost"], 1)


if __name__ == "__main__":
    unittest.main()
