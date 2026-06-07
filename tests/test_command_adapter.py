import tempfile
import unittest
from pathlib import Path

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.command import build_docker_command, render_command
from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


ROOT = Path(__file__).resolve().parents[1]


class CommandAdapterTest(unittest.TestCase):
    def test_render_command_with_docker_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli.yaml")
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=Path(tmp),
                prompt="hello",
                prompt_file=Path(tmp) / ".benchmark_prompt.txt",
                timeout_sec=10,
            )
            rendered = render_command(
                "agent --prompt {prompt_file} --workspace {workspace}",
                context,
                workspace_override="/workspace",
                prompt_file_override="/workspace/.benchmark_prompt.txt",
            )
            self.assertEqual(rendered, "agent --prompt /workspace/.benchmark_prompt.txt --workspace /workspace")

    def test_build_docker_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli-docker.yaml")
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=Path(tmp),
                prompt="hello",
                prompt_file=Path(tmp) / ".benchmark_prompt.txt",
                timeout_sec=10,
            )
            command = build_docker_command(harness.command or "", context)
            self.assertEqual(command[:4], ["docker", "run", "--rm", "-i"])
            self.assertIn("harness-efficiency-bench=true", command)
            self.assertIn("harness-efficiency-bench.run_id=run", command)
            self.assertIn("alpine:3.20", command)
            self.assertIn("-w", command)
            self.assertIn("/workspace", command)
            self.assertIn("GIT_CONFIG_KEY_0=safe.directory", command)
            self.assertIn("GIT_CONFIG_VALUE_0=/workspace", command)


if __name__ == "__main__":
    unittest.main()
