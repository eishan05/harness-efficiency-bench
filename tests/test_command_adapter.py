import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.command import build_docker_command, render_command, run_docker_command
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

    def test_build_docker_command_does_not_put_secret_env_values_in_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli-docker.yaml")
            harness.env["OPENROUTER_API_KEY"] = "sk-test-secret"
            harness.config["docker_env_passthrough"] = ["OPENAI_API_KEY"]
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=Path(tmp),
                prompt="hello",
                prompt_file=Path(tmp) / ".benchmark_prompt.txt",
                timeout_sec=10,
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-host-secret"}):
                command = build_docker_command(harness.command or "", context)

            self.assertIn("OPENROUTER_API_KEY", command)
            self.assertIn("OPENAI_API_KEY", command)
            self.assertNotIn("OPENROUTER_API_KEY=sk-test-secret", command)
            self.assertNotIn("OPENAI_API_KEY=sk-host-secret", command)

    def test_run_docker_command_merges_harness_env_into_subprocess_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli-docker.yaml")
            harness.env["OPENROUTER_API_KEY"] = "sk-test-secret"
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=Path(tmp),
                prompt="hello",
                prompt_file=Path(tmp) / ".benchmark_prompt.txt",
                timeout_sec=10,
            )

            with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run_mock:
                run_docker_command(harness.command or "", context)

            self.assertEqual(run_mock.call_args.kwargs["env"]["OPENROUTER_API_KEY"], "sk-test-secret")

    def test_run_docker_command_cleans_container_on_timeout(self):
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

            timeout = subprocess.TimeoutExpired(["docker"], 10, output="partial", stderr="tool stderr")
            with patch(
                "subprocess.run",
                side_effect=[
                    timeout,
                    subprocess.CompletedProcess(["docker", "ps"], 0, "abc123\n", ""),
                    subprocess.CompletedProcess(["docker", "rm"], 0, "", ""),
                ],
            ) as run_mock:
                completed = run_docker_command(harness.command or "", context)

            self.assertEqual(completed.returncode, 124)
            self.assertEqual(completed.stdout, "partial")
            self.assertIn("tool stderr", completed.stderr)
            self.assertIn("Command timed out after 10 seconds", completed.stderr)
            self.assertEqual(run_mock.call_args_list[1].args[0][:3], ["docker", "ps", "-aq"])
            self.assertEqual(run_mock.call_args_list[2].args[0], ["docker", "rm", "-f", "abc123"])

    def test_build_docker_command_can_add_host_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli-docker.yaml")
            harness.config["docker_add_host_gateway"] = True
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

            self.assertIn("--add-host", command)
            self.assertIn("host.docker.internal:host-gateway", command)

    def test_build_docker_command_renders_host_user_and_tmpfs_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
            harness = HarnessManifest.load(ROOT / "examples/harnesses/generic-cli-docker.yaml")
            harness.config["docker_user"] = "host"
            harness.config["docker_tmpfs"] = ["/home:uid={uid},gid={gid},mode=700"]
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

            self.assertIn(f"{os.getuid()}:{os.getgid()}", command)
            self.assertIn(f"/home:uid={os.getuid()},gid={os.getgid()},mode=700", command)


if __name__ == "__main__":
    unittest.main()
