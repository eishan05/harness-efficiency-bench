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

    def test_codex_and_claude_docker_examples_pin_cli_versions(self):
        paths = [
            ROOT / "examples/harnesses/claude-code-docker-isolated.yaml",
            ROOT / "examples/harnesses/claude-code-docker-openrouter.yaml",
            ROOT / "examples/harnesses/codex-docker-cheap.yaml",
            ROOT / "examples/harnesses/codex-docker-isolated.yaml",
            ROOT / "examples/harnesses/codex-docker-openrouter.yaml",
        ]
        for path in paths:
            harness = HarnessManifest.load(path)
            with self.subTest(path=path.name):
                self.assertEqual(harness.config.get("backend"), "docker")
                self.assertTrue(harness.config.get("cli_version"))
                self.assertTrue(harness.config.get("version_command"))

    def test_qwen_docker_examples_expose_run_limits(self):
        paths = [
            ROOT / "examples/harnesses/qwen-code-docker-isolated.yaml",
            ROOT / "examples/harnesses/qwen-code-docker-openrouter.yaml",
        ]
        for path in paths:
            harness = HarnessManifest.load(path)
            env_passthrough = harness.config.get("docker_env_passthrough", [])
            with self.subTest(path=path.name):
                self.assertIn("QWEN_MAX_SESSION_TURNS", env_passthrough)
                self.assertIn("QWEN_MAX_TOOL_CALLS", env_passthrough)
                self.assertIn("QWEN_MAX_WALL_TIME", env_passthrough)

    def test_docker_agent_examples_expose_wall_time_limits(self):
        expected = {
            "aider": ["AIDER_MAX_WALL_TIME"],
            "hermes-agent": ["HERMES_MAX_WALL_TIME"],
            "kilo": ["KILO_MAX_WALL_TIME"],
            "kimi-code": ["KIMI_MAX_WALL_TIME"],
            "openclaw": ["OPENCLAW_TIMEOUT_SEC", "OPENCLAW_MAX_WALL_TIME"],
            "opencode": ["OPENCODE_MAX_WALL_TIME"],
        }
        for harness_name, env_names in expected.items():
            paths = [
                ROOT / f"examples/harnesses/{harness_name}-docker-isolated.yaml",
                ROOT / f"examples/harnesses/{harness_name}-docker-openrouter.yaml",
            ]
            for path in paths:
                harness = HarnessManifest.load(path)
                env_passthrough = harness.config.get("docker_env_passthrough", [])
                with self.subTest(path=path.name):
                    for env_name in env_names:
                        self.assertIn(env_name, env_passthrough)


if __name__ == "__main__":
    unittest.main()
