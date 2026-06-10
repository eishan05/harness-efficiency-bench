import unittest

from harness_efficiency_bench.metrics import (
    compute_run_metrics,
    research_metric_coverage,
    usage_token_cost_cache_discounted,
)
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

    def test_startup_tax_unsupported_when_reported_input_is_below_prompt_estimate(self):
        prompt = "fix the bug " * 100
        events = [
            model_call_event(call_index=0, input_tokens=5, output_tokens=1),
            model_call_event(call_index=1, input_tokens=8, output_tokens=1),
        ]

        metrics = compute_run_metrics(events, count_tokens(prompt))

        self.assertEqual(metrics["startup_tax"]["status"], "unsupported")
        self.assertIsNone(metrics["startup_tax"]["value"])
        self.assertIn("below the benchmark prompt token estimate", metrics["startup_tax"]["details"]["reason"])

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
        # x is the turn position within the conversation thread; the
        # aggregate call between the two real calls is not a turn.
        self.assertEqual(metrics["context_growth_rate"]["details"]["points"], [(0.0, 10.0), (1.0, 20.0)])
        self.assertEqual(metrics["context_growth_rate"]["details"]["call_indices"], [0, 2])
        self.assertEqual(metrics["context_growth_rate"]["value"], 10.0)

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
        self.assertEqual(metrics["context_growth_rate"]["details"]["points"], [(0.0, 100.0), (1.0, 120.0)])
        self.assertEqual(metrics["context_growth_rate"]["details"]["call_indices"], [1, 2])
        self.assertEqual(metrics["usage"]["input_tokens"], 270)

    def test_tiny_first_call_counts_as_auxiliary_preflight(self):
        # Opencode/Kilo shape: a small helper request (e.g. title generation)
        # precedes the first call that carries the injected agent context.
        prompt = "fix the bug"
        prompt_tokens = count_tokens(prompt)
        events = [
            model_call_event(call_index=0, input_tokens=672, output_tokens=8),
            model_call_event(call_index=1, input_tokens=7786, output_tokens=20),
            model_call_event(call_index=2, input_tokens=8071, output_tokens=20),
        ]

        metrics = compute_run_metrics(events, prompt_tokens)

        self.assertEqual(metrics["startup_tax"]["status"], "full")
        self.assertEqual(
            metrics["startup_tax"]["value"],
            (672 - prompt_tokens) + (7786 - prompt_tokens),
        )
        self.assertEqual(metrics["startup_tax"]["details"]["provider_first_call_index"], 0)
        self.assertEqual(metrics["startup_tax"]["details"]["task_first_call_index"], 1)
        self.assertEqual(metrics["startup_tax"]["details"]["auxiliary_preflight_call_indices"], [0])
        self.assertEqual(
            metrics["context_growth_rate"]["details"]["points"],
            [(0.0, 7786.0), (1.0, 8071.0)],
        )
        self.assertEqual(metrics["context_growth_rate"]["details"]["call_indices"], [1, 2])
        self.assertEqual(metrics["context_growth_rate"]["details"]["auxiliary_preflight_call_indices"], [0])

    def test_lean_first_call_is_not_auxiliary_preflight(self):
        # Aider-architect shape: a genuinely lean first call followed by a
        # moderately larger second call must stay the task-first call.
        prompt = "fix the bug"
        prompt_tokens = count_tokens(prompt)
        events = [
            model_call_event(call_index=0, input_tokens=739, output_tokens=50),
            model_call_event(call_index=1, input_tokens=1183, output_tokens=50),
        ]

        metrics = compute_run_metrics(events, prompt_tokens)

        self.assertEqual(metrics["startup_tax"]["value"], 739 - prompt_tokens)
        self.assertNotIn("auxiliary_preflight_call_indices", metrics["startup_tax"]["details"])
        self.assertEqual(len(metrics["context_growth_rate"]["details"]["points"]), 2)

    def test_large_first_call_is_not_auxiliary_preflight_despite_jump(self):
        # A first call already carrying a big injected context stays the
        # task-first call even if a large tool result lands on call two.
        prompt = "fix the bug"
        prompt_tokens = count_tokens(prompt)
        events = [
            model_call_event(call_index=0, input_tokens=4302, output_tokens=20),
            model_call_event(call_index=1, input_tokens=17000, output_tokens=20),
            model_call_event(call_index=2, input_tokens=17500, output_tokens=20),
        ]

        metrics = compute_run_metrics(events, prompt_tokens)

        self.assertEqual(metrics["startup_tax"]["value"], 4302 - prompt_tokens)
        self.assertNotIn("auxiliary_preflight_call_indices", metrics["startup_tax"]["details"])
        self.assertEqual(len(metrics["context_growth_rate"]["details"]["points"]), 3)

    def test_growth_fits_dominant_thread_and_excludes_interleaved_subthread(self):
        # Kilo shape: the main conversation is interrupted by a smaller
        # sub-conversation, then resumes. The slope must come from the main
        # thread only, measured per turn of that thread.
        inputs = [13000, 5800, 6100, 6900, 13900, 14600, 15000]
        events = [
            model_call_event(call_index=index, input_tokens=value, output_tokens=10)
            for index, value in enumerate(inputs)
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        growth = metrics["context_growth_rate"]
        self.assertEqual(growth["status"], "full")
        self.assertEqual(growth["details"]["call_indices"], [0, 4, 5, 6])
        self.assertEqual(growth["details"]["excluded_call_indices"], [1, 2, 3])
        self.assertEqual(growth["details"]["context_thread_sizes"], [4, 3])
        self.assertAlmostEqual(growth["value"], 670.0)

    def test_growth_keeps_small_dips_in_one_thread(self):
        # Small within-thread decreases (prompt trimming, token jitter) must
        # not split the conversation into separate threads.
        inputs = [10000, 9900, 10500, 10400, 11000]
        events = [
            model_call_event(call_index=index, input_tokens=value, output_tokens=10)
            for index, value in enumerate(inputs)
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        growth = metrics["context_growth_rate"]
        self.assertEqual(growth["details"]["call_indices"], [0, 1, 2, 3, 4])
        self.assertNotIn("excluded_call_indices", growth["details"])

    def test_token_cost_excludes_reasoning_nested_in_output(self):
        events = [
            model_call_event(
                call_index=0,
                input_tokens=100,
                output_tokens=80,
                reasoning_output_tokens=60,
                reasoning_in_output=True,
            ),
            model_call_event(
                call_index=1,
                input_tokens=120,
                output_tokens=40,
                reasoning_output_tokens=30,
            ),
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        usage = metrics["usage"]
        self.assertEqual(usage["reasoning_output_tokens"], 90)
        self.assertEqual(usage["reasoning_tokens_in_output"], 60)
        # Nested reasoning is already inside output_tokens; only the separate
        # 30 reasoning tokens are additive.
        self.assertEqual(usage["token_cost"], 100 + 80 + 120 + 40 + 30)

    def test_total_usage_skips_aggregate_calls_when_per_call_usage_exists(self):
        # Qwen shape: a final summary event repeats the cumulative session
        # usage. It must not be double-counted in solve-efficiency totals.
        events = [
            model_call_event(call_index=0, input_tokens=100, output_tokens=10),
            model_call_event(call_index=1, input_tokens=200, output_tokens=20),
            model_call_event(
                call_index=2,
                input_tokens=300,
                output_tokens=30,
                cost_usd=0.5,
                metadata={"aggregate": True, "aggregate_reason": "usage equals cumulative totals of prior model calls"},
            ),
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        usage = metrics["usage"]
        self.assertEqual(usage["input_tokens"], 300)
        self.assertEqual(usage["output_tokens"], 30)
        self.assertEqual(usage["token_cost"], 330)
        # The aggregate call carries the only cost; it stands in for totals.
        self.assertEqual(usage["cost_usd"], 0.5)
        self.assertTrue(usage["cost_available"])
        self.assertEqual(metrics["context_growth_rate"]["details"]["call_indices"], [0, 1])

    def test_unmarked_cumulative_summary_call_detected_structurally(self):
        # Traces recorded before adapters marked summary events still need
        # the cumulative call excluded when metrics are recomputed.
        events = [
            model_call_event(call_index=0, input_tokens=100, output_tokens=10),
            model_call_event(call_index=1, input_tokens=150, output_tokens=20),
            model_call_event(call_index=2, input_tokens=200, output_tokens=30),
            model_call_event(call_index=3, input_tokens=450, output_tokens=60),
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        self.assertEqual(metrics["usage"]["input_tokens"], 450)
        self.assertEqual(metrics["usage"]["token_cost"], 510)
        self.assertEqual(metrics["context_growth_rate"]["details"]["call_indices"], [0, 1, 2])

    def test_total_usage_still_uses_aggregate_only_runs(self):
        events = [
            model_call_event(
                call_index=0,
                input_tokens=500,
                output_tokens=50,
                metadata={"aggregate": True},
            )
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        self.assertEqual(metrics["usage"]["input_tokens"], 500)
        self.assertEqual(metrics["usage"]["token_cost"], 550)

    def test_model_mismatch_calls_are_excluded_from_task_first_and_growth(self):
        # Opencode/Kilo shape: helper requests (title generation) are billed
        # to a different model than the task conversation. The first helper is
        # large enough here to evade the size-based preflight heuristic, and a
        # second helper appears mid-run where the size heuristic never looks.
        prompt = "fix the bug"
        helper = {"model": "anthropic/claude-4.5-haiku"}
        task_model = {"model": "nvidia/nemotron"}
        events = [
            model_call_event(call_index=0, input_tokens=3000, output_tokens=10, metadata=dict(helper)),
            model_call_event(call_index=1, input_tokens=8000, output_tokens=50, metadata=dict(task_model)),
            model_call_event(call_index=2, input_tokens=8500, output_tokens=50, metadata=dict(task_model)),
            model_call_event(call_index=3, input_tokens=700, output_tokens=10, metadata=dict(helper)),
            model_call_event(call_index=4, input_tokens=9000, output_tokens=50, metadata=dict(task_model)),
        ]

        metrics = compute_run_metrics(events, count_tokens(prompt))

        startup = metrics["startup_tax"]
        self.assertEqual(startup["details"]["model_mismatch_call_indices"], [0, 3])
        self.assertEqual(startup["details"]["task_first_call_index"], 1)
        growth = metrics["context_growth_rate"]
        self.assertEqual(growth["details"]["model_mismatch_call_indices"], [0, 3])
        self.assertEqual(growth["details"]["call_indices"], [1, 2, 4])
        self.assertAlmostEqual(growth["value"], 500.0)
        # Helper calls still count toward solve-efficiency totals.
        self.assertEqual(metrics["usage"]["input_tokens"], 3000 + 8000 + 8500 + 700 + 9000)

    def test_single_model_runs_have_no_mismatch_exclusions(self):
        events = [
            model_call_event(call_index=0, input_tokens=1000, output_tokens=10, metadata={"model": "m"}),
            model_call_event(call_index=1, input_tokens=2000, output_tokens=10, metadata={"model": "m"}),
        ]

        metrics = compute_run_metrics(events, user_prompt_tokens=0)

        self.assertNotIn("model_mismatch_call_indices", metrics["startup_tax"]["details"])
        self.assertNotIn("model_mismatch_call_indices", metrics["context_growth_rate"]["details"])

    def test_cache_discounted_token_cost_weights_cache_reads(self):
        usage = {"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 100}

        # 600 cached input tokens billed at 0.1 weight: 1100 - 600 * 0.9.
        self.assertAlmostEqual(usage_token_cost_cache_discounted(usage), 560.0)

    def test_total_usage_includes_cache_discounted_cost_and_by_model(self):
        events = [
            model_call_event(
                call_index=0,
                input_tokens=1000,
                cached_input_tokens=400,
                output_tokens=20,
                metadata={"model": "a"},
            ),
            model_call_event(
                call_index=1,
                input_tokens=2000,
                cached_input_tokens=1500,
                output_tokens=30,
                metadata={"model": "b"},
            ),
        ]

        usage = compute_run_metrics(events, user_prompt_tokens=0)["usage"]

        self.assertEqual(usage["token_cost"], 3050)
        self.assertAlmostEqual(usage["token_cost_cache_discounted"], 3050 - 1900 * 0.9)
        self.assertEqual(
            usage["by_model"],
            {
                "a": {"calls": 1, "input_tokens": 1000, "output_tokens": 20},
                "b": {"calls": 1, "input_tokens": 2000, "output_tokens": 30},
            },
        )

    def test_growth_flags_slope_median_divergence(self):
        # A single extreme jump dominates the least-squares slope while the
        # median adjacent delta stays small — the signature of an aggregate
        # point or thread that slipped past structural detection.
        events = [
            model_call_event(call_index=index, input_tokens=tokens, output_tokens=1)
            for index, tokens in enumerate([1000, 1010, 1020, 1030, 9000])
        ]

        growth = compute_run_metrics(events, user_prompt_tokens=0)["context_growth_rate"]

        self.assertEqual(growth["details"]["median_adjacent_delta"], 10.0)
        self.assertTrue(growth["details"]["slope_median_divergence"])

    def test_growth_does_not_flag_linear_thread(self):
        events = [
            model_call_event(call_index=index, input_tokens=1000 + 500 * index, output_tokens=1)
            for index in range(4)
        ]

        growth = compute_run_metrics(events, user_prompt_tokens=0)["context_growth_rate"]

        self.assertEqual(growth["details"]["median_adjacent_delta"], 500.0)
        self.assertNotIn("slope_median_divergence", growth["details"])

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
