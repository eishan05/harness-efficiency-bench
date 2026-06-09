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
    DEFAULT_DOCKER_SOCKET,
    DEFAULT_SWE_BENCH_ORACLE_IMAGE,
    build_swe_bench_docker_command,
    build_swe_bench_eval_command,
    fetch_swe_bench_rows,
    resolve_swe_bench_arch,
    resolve_swe_bench_namespace,
    write_swe_bench_arch_wrapper,
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
        self.assertIn("backend: docker", manifest_text)
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
            spec = OracleSpec.from_dict({"type": "swe_bench", "backend": "host", "instance_id": "x"})
            with patch("importlib.util.find_spec", return_value=None):
                result = grade_oracle(spec, Path(tmp))

        self.assertFalse(result.success)
        self.assertIn("swebench package is not installed", result.message)

    def test_swe_bench_host_oracle_runs_evaluator_and_parses_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            spec = OracleSpec.from_dict(
                {
                    "type": "swe_bench",
                    "backend": "host",
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
                self.assertTrue(any(str(item).endswith("swebench_arch_wrapper.py") for item in command))
                self.assertIn("--instance_ids", command)
                self.assertIn("django__django-11905", command)
                self.assertEqual(kwargs["env"]["SWEBENCH_ARCH"], resolve_swe_bench_arch("auto"))
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

    def test_swe_bench_docker_oracle_runs_without_host_swebench(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            docker_socket = Path(tmp) / "docker.sock"
            docker_socket.touch()
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
                    "docker_socket": str(docker_socket),
                    "evaluator_image": "harness-bench/swebench-oracle:test",
                }
            )

            def fake_run(command, **kwargs):
                self.assertEqual(command[:3], ["docker", "run", "--rm"])
                self.assertIn("harness-bench/swebench-oracle:test", command)
                self.assertIn("--user", command)
                self.assertIn("--group-add", command)
                self.assertIn(f"{docker_socket}:{docker_socket}", command)
                self.assertTrue(any(str(item).endswith("swebench_arch_wrapper.py") for item in command))
                self.assertIn("SWEBENCH_ARCH=" + resolve_swe_bench_arch("auto"), command)
                eval_root = Path(kwargs["cwd"])
                self.assertIn(f"{eval_root}:{eval_root}", command)
                self.assertIn("python", command)
                self.assertIn("django__django-11905", command)
                report_path = eval_root / "test__model.run-1.json"
                report_path.write_text(
                    json.dumps({"resolved_ids": ["django__django-11905"], "schema_version": 2}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("importlib.util.find_spec", side_effect=AssertionError("host swebench should not be checked")):
                with patch("subprocess.run", side_effect=fake_run):
                    result = grade_oracle(spec, workspace)

        self.assertTrue(result.success)
        self.assertEqual(result.details["backend"], "docker")
        self.assertEqual(result.details["evaluator_image"], "harness-bench/swebench-oracle:test")
        self.assertEqual(result.details["docker_socket"], str(docker_socket))

    def test_swe_bench_docker_command_uses_same_absolute_eval_root(self):
        eval_root = Path("/tmp/harness-run/swebench_eval")

        command = build_swe_bench_docker_command(
            eval_command=["python", "-m", "swebench.harness.run_evaluation"],
            eval_root=eval_root,
        )

        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn(DEFAULT_SWE_BENCH_ORACLE_IMAGE, command)
        self.assertIn(f"{DEFAULT_DOCKER_SOCKET}:{DEFAULT_DOCKER_SOCKET}", command)
        self.assertIn("--user", command)
        self.assertIn("--group-add", command)
        self.assertIn(f"{eval_root}:{eval_root}", command)
        self.assertIn(str(eval_root), command)
        self.assertIn(f"HOME={eval_root}", command)
        self.assertIn(f"HF_HOME={eval_root / '.cache' / 'huggingface'}", command)
        self.assertIn(f"HF_DATASETS_CACHE={eval_root / '.cache' / 'huggingface' / 'datasets'}", command)
        self.assertIn(f"HUGGINGFACE_HUB_CACHE={eval_root / '.cache' / 'huggingface' / 'hub'}", command)

    def test_swe_bench_arch_and_namespace_resolution(self):
        with patch("platform.machine", return_value="aarch64"):
            self.assertEqual(resolve_swe_bench_arch("auto"), "arm64")
        with patch("platform.machine", return_value="x86_64"):
            self.assertEqual(resolve_swe_bench_arch("host"), "x86_64")
        self.assertEqual(resolve_swe_bench_arch("amd64"), "x86_64")
        self.assertEqual(resolve_swe_bench_arch("aarch64"), "arm64")
        self.assertIsNone(resolve_swe_bench_namespace("auto", arch="arm64"))
        self.assertEqual(resolve_swe_bench_namespace("auto", arch="x86_64"), "swebench")
        self.assertIsNone(resolve_swe_bench_namespace("none", arch="x86_64"))
        self.assertEqual(resolve_swe_bench_namespace("custom", arch="arm64"), "custom")

    def test_swe_bench_eval_command_can_use_arch_wrapper_and_no_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            eval_root = Path(tmp)
            wrapper = write_swe_bench_arch_wrapper(eval_root)
            command = build_swe_bench_eval_command(
                dataset_name="SWE-bench/SWE-bench_Lite",
                split="test",
                instance_id="django__django-11905",
                predictions_path=eval_root / "predictions.jsonl",
                run_id="run-1",
                max_workers=1,
                cache_level="env",
                timeout_sec=1800,
                namespace=None,
                python_executable="python",
                wrapper_path=wrapper,
            )
            wrapper_text = wrapper.read_text(encoding="utf-8")

        self.assertEqual(command[:2], ["python", str(wrapper)])
        self.assertIn("--namespace", command)
        self.assertIn("none", command)
        self.assertIn("make_test_spec_for_arch", wrapper_text)

    def test_swe_bench_docker_command_can_pass_arch_env(self):
        eval_root = Path("/tmp/harness-run/swebench_eval")

        command = build_swe_bench_docker_command(
            eval_command=["python", "swebench_arch_wrapper.py"],
            eval_root=eval_root,
            swe_bench_arch="arm64",
        )

        self.assertIn("SWEBENCH_ARCH=arm64", command)


if __name__ == "__main__":
    unittest.main()
