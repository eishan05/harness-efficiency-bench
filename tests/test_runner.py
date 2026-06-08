import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_efficiency_bench.adapters.base import AdapterResult
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

    def test_collect_git_diff_excludes_codex_rollout_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            BenchmarkRunner._run_setup_command(["git", "init"], workspace)
            BenchmarkRunner._run_setup_command(["git", "config", "user.email", "benchmark@example.invalid"], workspace)
            BenchmarkRunner._run_setup_command(["git", "config", "user.name", "Harness Benchmark"], workspace)
            (workspace / "tracked.txt").write_text("before\n", encoding="utf-8")
            BenchmarkRunner._run_setup_command(["git", "add", "-A"], workspace)
            BenchmarkRunner._run_setup_command(["git", "commit", "-m", "baseline"], workspace)

            (workspace / "tracked.txt").write_text("after\n", encoding="utf-8")
            trace_dir = workspace / ".codex_rollout_trace" / "trace-1"
            trace_dir.mkdir(parents=True)
            (trace_dir / "trace.jsonl").write_text('{"payload": "large"}\n', encoding="utf-8")
            cache_dir = workspace / "pkg" / "__pycache__"
            cache_dir.mkdir(parents=True)
            (cache_dir / "module.cpython-311.pyc").write_bytes(b"cache")
            root_cache_dir = workspace / "__pycache__"
            root_cache_dir.mkdir()
            (root_cache_dir / "parser.cpython-312.pyc").write_bytes(b"root-cache")

            diff = BenchmarkRunner._collect_git_diff(workspace)

        self.assertIn("tracked.txt", diff)
        self.assertNotIn(".codex_rollout_trace", diff)
        self.assertNotIn("__pycache__", diff)

    def test_git_clone_workspace_setup_uses_repo_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            BenchmarkRunner._run_setup_command(["git", "init"], source)
            BenchmarkRunner._run_setup_command(["git", "config", "user.email", "benchmark@example.invalid"], source)
            BenchmarkRunner._run_setup_command(["git", "config", "user.name", "Harness Benchmark"], source)
            (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            BenchmarkRunner._run_setup_command(["git", "add", "-A"], source)
            BenchmarkRunner._run_setup_command(["git", "commit", "-m", "baseline"], source)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout.strip()

            workspace = root / "workspace"
            workspace.mkdir()
            task = TaskManifest(
                id="git-task",
                prompt="fix it",
                path=root / "task.yaml",
                workspace_setup={"git_clone": {"repo": str(source), "base_commit": commit}},
            )
            runner = BenchmarkRunner(root / "runs", repo_cache=root / "repo-cache")
            runner._setup_workspace(task, workspace)

            self.assertEqual((workspace / "module.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertTrue((root / "repo-cache").exists())
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout.strip()
            self.assertEqual(head, commit)

    def test_run_uses_adapter_reported_model_id(self):
        class StubAdapter:
            def run(self, context):
                return AdapterResult(exit_code=0, metadata={"model_id": "resolved/model"})

        with tempfile.TemporaryDirectory() as tmp:
            runner = BenchmarkRunner(tmp)
            task = TaskManifest(id="task", prompt="prompt", path=Path(tmp) / "task.yaml")
            harness = HarnessManifest(
                id="harness",
                adapter="stub",
                path=Path(tmp) / "harness.yaml",
                model="${MODEL}",
            )
            with patch("harness_efficiency_bench.runner.create_adapter", return_value=StubAdapter()):
                result = runner.run_task(task, harness, keep_workspace=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["model_id"], "resolved/model")

    def test_summary(self):
        summary = summarize_results(
            [
                {
                    "success": True,
                    "harness_id": "a",
                    "metrics": {
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "reasoning_output_tokens": 3,
                            "cost_usd": 2.0,
                            "cost_available": True,
                        }
                    },
                }
            ]
        )
        self.assertEqual(summary["attempted"], 1)
        self.assertEqual(summary["solved"], 1)
        self.assertEqual(summary["token_cost"], 15)
        self.assertEqual(summary["token_cost_per_solved_task"], 15.0)
        self.assertEqual(summary["dollar_cost_per_solved_task"], 2.0)
        self.assertEqual(summary["by_harness"]["a"]["token_cost_per_solved_task"], 15.0)
        self.assertEqual(summary["by_harness"]["a"]["dollar_cost_per_solved_task"], 2.0)
        self.assertIn("metrics", summary["by_harness"]["a"])
        self.assertEqual(summary["by_perturbation"]["base"]["solve_rate"], 1.0)
        self.assertIn("research_metric_coverage", summary)

    def test_summary_token_solve_efficiency_works_when_dollar_cost_missing(self):
        summary = summarize_results(
            [
                {
                    "success": True,
                    "harness_id": "a",
                    "metrics": {
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "cost_usd": 0.0,
                            "cost_available": False,
                        }
                    },
                }
            ]
        )

        self.assertEqual(summary["token_cost_per_solved_task"], 12.0)
        self.assertEqual(summary["by_harness"]["a"]["token_cost_per_solved_task"], 12.0)
        self.assertIsNone(summary["dollar_cost_per_solved_task"])
        self.assertIsNone(summary["by_harness"]["a"]["dollar_cost_per_solved_task"])


if __name__ == "__main__":
    unittest.main()
