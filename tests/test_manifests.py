import unittest
from pathlib import Path

from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


ROOT = Path(__file__).resolve().parents[1]


class ManifestTest(unittest.TestCase):
    def test_load_task_manifest(self):
        task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
        self.assertEqual(task.id, "toy-write-file")
        self.assertEqual(task.oracle.type, "file_equals")
        self.assertTrue(task.workspace_setup["git_init"])
        self.assertEqual(task.perturbation("20k").tokens, 20000)

    def test_load_swe_bench_task_manifest(self):
        task = TaskManifest.load(
            ROOT / "examples/tasks/swe-bench-lite-curated-10/django__django-11905/task.yaml"
        )
        self.assertEqual(task.id, "django__django-11905")
        self.assertEqual(task.source, "swe-bench-lite")
        self.assertEqual(task.oracle.type, "swe_bench")
        self.assertEqual(task.oracle.data["backend"], "docker")
        self.assertEqual(task.oracle.data["instance_id"], "django__django-11905")
        self.assertEqual(task.workspace_setup["git_clone"]["repo"], "django/django")

    def test_swe_bench_lite_curated_tasks_use_docker_oracle(self):
        paths = sorted((ROOT / "examples/tasks/swe-bench-lite-curated-10").glob("*/task.yaml"))
        self.assertTrue(paths)
        for path in paths:
            task = TaskManifest.load(path)
            with self.subTest(path=path.name):
                self.assertEqual(task.oracle.type, "swe_bench")
                self.assertEqual(task.oracle.data.get("backend"), "docker")

    def test_load_harness_manifest(self):
        harness = HarnessManifest.load(ROOT / "examples/harnesses/demo.yaml")
        self.assertEqual(harness.id, "demo")
        self.assertEqual(harness.adapter, "demo")

    def test_all_example_harnesses_load(self):
        for path in sorted((ROOT / "examples/harnesses").glob("*.yaml")):
            with self.subTest(path=path.name):
                harness = HarnessManifest.load(path)
                self.assertTrue(harness.id)
                self.assertTrue(harness.adapter)

    def test_docker_agent_cli_examples_are_docker_only_and_versioned(self):
        paths = sorted((ROOT / "examples/harnesses").glob("*-docker-isolated.yaml"))
        self.assertTrue(paths)
        for path in paths:
            harness = HarnessManifest.load(path)
            if harness.adapter != "docker_agent_cli":
                continue
            with self.subTest(path=path.name):
                self.assertEqual(harness.config.get("backend"), "docker")
                self.assertIn("docker_isolation", harness.capabilities)
                self.assertTrue(harness.config.get("docker_image"))
                self.assertTrue(harness.config.get("cli_version"))
                self.assertTrue(harness.config.get("version_command"))

    def test_docker_examples_run_as_host_user(self):
        paths = sorted((ROOT / "examples/harnesses").glob("*docker*.yaml"))
        self.assertTrue(paths)
        for path in paths:
            harness = HarnessManifest.load(path)
            if harness.config.get("backend") != "docker":
                continue
            with self.subTest(path=path.name):
                self.assertEqual(harness.config.get("docker_user"), "host")

    def test_openrouter_docker_examples_require_key_and_model(self):
        paths = sorted((ROOT / "examples/harnesses").glob("*-docker-openrouter.yaml"))
        self.assertTrue(paths)
        ids = {HarnessManifest.load(path).id for path in paths}
        self.assertTrue(
            {
                "claude-code-docker-openrouter",
                "aider-docker-openrouter",
                "codex-docker-openrouter",
                "goose-docker-openrouter",
                "hermes-agent-docker-openrouter",
                "kilo-docker-openrouter",
                "kimi-code-docker-openrouter",
                "nanobot-docker-openrouter",
                "openclaw-docker-openrouter",
                "opencode-docker-openrouter",
                "qwen-code-docker-openrouter",
            }.issubset(ids)
        )
        for path in paths:
            harness = HarnessManifest.load(path)
            with self.subTest(path=path.name):
                if harness.id == "claude-code-docker-openrouter":
                    self.assertEqual(harness.adapter, "claude_code")
                elif harness.id == "codex-docker-openrouter":
                    self.assertEqual(harness.adapter, "codex")
                else:
                    self.assertEqual(harness.adapter, "docker_agent_cli")
                self.assertEqual(harness.config.get("backend"), "docker")
                self.assertIn("docker_isolation", harness.capabilities)
                self.assertIn("OPENROUTER_API_KEY", harness.config.get("docker_env_passthrough", []))
                self.assertIn("OPENROUTER_MODEL", harness.config.get("docker_env_passthrough", []))
                self.assertIn("OPENROUTER_API_KEY", harness.config.get("required_env", []))
                self.assertIn("OPENROUTER_MODEL", harness.config.get("required_env", []))


if __name__ == "__main__":
    unittest.main()
