import tempfile
import unittest
from pathlib import Path

from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest
from harness_efficiency_bench.runner import BenchmarkRunner, summarize_results


ROOT = Path(__file__).resolve().parents[1]


class RunnerTest(unittest.TestCase):
    def test_demo_run_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = BenchmarkRunner(tmp)
            result = runner.run_task(
                TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml"),
                HarnessManifest.load(ROOT / "examples/harnesses/demo.yaml"),
            )
            self.assertTrue(result["success"])
            self.assertTrue(Path(result["trace_path"]).exists())
            self.assertEqual(result["metrics"]["startup_tax"]["status"], "full")
            self.assertIn("answer.txt", result["artifacts"]["git_diff"])
            self.assertNotIn(".benchmark_prompt.txt", result["artifacts"]["git_diff"])

    def test_summary(self):
        summary = summarize_results([{"success": True, "harness_id": "a", "metrics": {"usage": {"cost_usd": 2.0}}}])
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["solved"], 1)
        self.assertEqual(summary["cost_per_solved_task"], 2.0)
        self.assertIn("metrics", summary["by_harness"]["a"])
        self.assertEqual(summary["by_perturbation"]["base"]["solve_rate"], 1.0)
        self.assertIn("research_metric_coverage", summary)


if __name__ == "__main__":
    unittest.main()
