import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.docker_agent_cli import (
    DockerAgentCliAdapter,
    parse_docker_agent_events,
    parse_proxy_trace_events,
)
from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


class DockerAgentCliAdapterTest(unittest.TestCase):
    def test_rejects_host_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = HarnessManifest(
                id="host-agent",
                adapter="docker_agent_cli",
                path=root / "harness.yaml",
                command=["agent"],
                config={},
            )
            task = TaskManifest(id="task", prompt="prompt", path=root / "task.yaml")

            result = DockerAgentCliAdapter(harness).run(
                AdapterRunContext(
                    run_id="run",
                    task=task,
                    harness=harness,
                    workspace=root,
                    prompt="prompt",
                    prompt_file=root / ".benchmark_prompt.txt",
                    timeout_sec=1,
                )
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("config.backend: docker", result.stderr)

    def test_missing_required_env_fails_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = HarnessManifest(
                id="docker-agent",
                adapter="docker_agent_cli",
                path=root / "harness.yaml",
                command=["agent"],
                config={
                    "backend": "docker",
                    "docker_image": "missing-image",
                    "required_env": ["HARNESS_BENCH_TEST_MISSING_KEY"],
                },
            )
            task = TaskManifest(id="task", prompt="prompt", path=root / "task.yaml")

            result = DockerAgentCliAdapter(harness).run(
                AdapterRunContext(
                    run_id="run",
                    task=task,
                    harness=harness,
                    workspace=root,
                    prompt="prompt",
                    prompt_file=root / ".benchmark_prompt.txt",
                    timeout_sec=1,
                )
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("HARNESS_BENCH_TEST_MISSING_KEY", result.stderr)

    def test_empty_required_env_fails_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {"HARNESS_BENCH_TEST_EMPTY_KEY": ""}, clear=False
        ):
            root = Path(tmp)
            harness = HarnessManifest(
                id="docker-agent",
                adapter="docker_agent_cli",
                path=root / "harness.yaml",
                command=["agent"],
                config={
                    "backend": "docker",
                    "docker_image": "missing-image",
                    "required_env": ["HARNESS_BENCH_TEST_EMPTY_KEY"],
                },
            )
            task = TaskManifest(id="task", prompt="prompt", path=root / "task.yaml")

            result = DockerAgentCliAdapter(harness).run(
                AdapterRunContext(
                    run_id="run",
                    task=task,
                    harness=harness,
                    workspace=root,
                    prompt="prompt",
                    prompt_file=root / ".benchmark_prompt.txt",
                    timeout_sec=1,
                )
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("HARNESS_BENCH_TEST_EMPTY_KEY", result.stderr)

    def test_parse_native_jsonl_usage_and_tool_result(self):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                        "response_cost": 0.001,
                    }
                ),
                json.dumps({"role": "tool", "tool_call_id": "shell", "content": "pytest failed"}),
            ]
        )

        events = parse_docker_agent_events(stdout, {"trace": {"parser": "goose_stream_json"}})

        model_calls = [event for event in events if event.type == "model_call"]
        tool_results = [event for event in events if event.type == "tool_result"]
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 10)
        self.assertEqual(model_calls[0].data["output_tokens"], 3)
        self.assertEqual(model_calls[0].data["cost_usd"], 0.001)
        self.assertEqual(tool_results[0].data["output"], "pytest failed")

    def test_parse_proxy_usage_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".litellm-usage.jsonl").write_text(
                json.dumps(
                    {
                        "model": "openai/gpt-4o-mini",
                        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                        "metadata": {"response_cost": 0.002},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            events = parse_proxy_trace_events(workspace, {"trace": {"litellm_log_path": ".litellm-usage.jsonl"}})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].data["input_tokens"], 12)
        self.assertEqual(events[0].data["output_tokens"], 4)
        self.assertEqual(events[0].data["metadata"]["source"], "litellm_proxy")


if __name__ == "__main__":
    unittest.main()
