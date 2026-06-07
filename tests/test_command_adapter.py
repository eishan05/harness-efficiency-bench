import tempfile
import unittest
from pathlib import Path

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.command import render_command
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


if __name__ == "__main__":
    unittest.main()

