import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_efficiency_bench.manifests import OracleSpec
from harness_efficiency_bench.cli import main
from harness_efficiency_bench.oracles import grade_oracle
from harness_efficiency_bench.swe_bench import (
    CURATED_10_INSTANCE_IDS,
    fetch_swe_bench_rows,
    write_swe_bench_task_manifests,
)


class SweBenchTest(unittest.TestCase):
    def test_fetch_rows_returns_curated_order(self):
        rows = [
            {"row": {"instance_id": CURATED_10_INSTANCE_IDS[1], "repo": "django/django"}},
            {"row": {"instance_id": CURATED_10_INSTANCE_IDS[0], "repo": "django/django"}},
        ]

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(url, timeout=30):
            self.assertIn("SWE-bench%2FSWE-bench_Lite", url)
            response = FakeResponse()
            response.read = lambda: json.dumps({"rows": rows}).encode("utf-8")
            return response

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            fetched = fetch_swe_bench_rows(instance_ids=CURATED_10_INSTANCE_IDS[:2])

        self.assertEqual([item["instance_id"] for item in fetched], list(CURATED_10_INSTANCE_IDS[:2]))

    def test_write_task_manifests_do_not_include_gold_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                {
                    "instance_id": "django__django-11905",
                    "repo": "django/django",
                    "base_commit": "abc123",
                    "problem_statement": "Fix the bug.\r\nDo not regress.",
                    "patch": "diff --git a/gold b/gold",
                    "test_patch": "diff --git a/test b/test",
                }
            ]
            written = write_swe_bench_task_manifests(rows, Path(tmp))
            manifest_text = written[0].read_text(encoding="utf-8")
            prompt_text = (written[0].parent / "prompt.txt").read_text(encoding="utf-8")

        self.assertIn("oracle:\n  type: swe_bench", manifest_text)
        self.assertIn("repo: django/django", manifest_text)
        self.assertEqual(prompt_text, "Fix the bug.\nDo not regress.\n")
        self.assertNotIn("test_patch", manifest_text + prompt_text)
        self.assertNotIn("diff --git", manifest_text + prompt_text)

    def test_import_cli_writes_tasks(self):
        rows = [
            {
                "instance_id": "django__django-11905",
                "repo": "django/django",
                "base_commit": "abc123",
                "problem_statement": "Fix the bug.",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tasks"
            stream = io.StringIO()
            with patch("harness_efficiency_bench.cli.CURATED_10_INSTANCE_IDS", ("django__django-11905",)):
                with patch("harness_efficiency_bench.cli.fetch_swe_bench_rows", return_value=rows):
                    with contextlib.redirect_stdout(stream):
                        code = main(["import-swe-bench-lite", "--out-dir", str(out)])

            payload = json.loads(stream.getvalue())
            manifest = out / "django__django-11905" / "task.yaml"
            manifest_exists = manifest.exists()

        self.assertEqual(code, 0)
        self.assertEqual(payload["count"], 1)
        self.assertTrue(manifest_exists)

    def test_swe_bench_oracle_reports_missing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = OracleSpec.from_dict({"type": "swe_bench", "instance_id": "x"})
            with patch("importlib.util.find_spec", return_value=None):
                result = grade_oracle(spec, Path(tmp))

        self.assertFalse(result.success)
        self.assertIn("swebench package is not installed", result.message)

    def test_swe_bench_oracle_runs_evaluator_and_parses_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            spec = OracleSpec.from_dict(
                {
                    "type": "swe_bench",
                    "dataset_name": "SWE-bench/SWE-bench_Lite",
                    "split": "test",
                    "instance_id": "django__django-11905",
                    "model_name_or_path": "test/model",
                    "run_id": "run-1",
                    "max_workers": 1,
                    "cache_level": "env",
                    "timeout_sec": 1800,
                }
            )

            def fake_run(command, **kwargs):
                self.assertIn("swebench.harness.run_evaluation", command)
                self.assertIn("--instance_ids", command)
                self.assertIn("django__django-11905", command)
                eval_root = Path(kwargs["cwd"])
                report_path = eval_root / "test__model.run-1.json"
                report_path.write_text(
                    json.dumps({"resolved_ids": ["django__django-11905"], "schema_version": 2}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("importlib.util.find_spec", return_value=object()):
                with patch("subprocess.run", side_effect=fake_run):
                    result = grade_oracle(spec, workspace)

        self.assertTrue(result.success)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.details["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
