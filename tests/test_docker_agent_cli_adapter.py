import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.docker_agent_cli import (
    DockerAgentCliAdapter,
    _select_trace_events,
    parse_docker_agent_events,
    parse_proxy_trace_events,
)
from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest
from harness_efficiency_bench.tracing import model_call_event, tool_result_event


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

    def test_parse_opencode_step_finish_tokens(self):
        stdout = json.dumps(
            {
                "type": "step_finish",
                "part": {
                    "tokens": {
                        "input": 7977,
                        "output": 38,
                        "reasoning": 35,
                        "cache": {"read": 12, "write": 0},
                    },
                    "cost": 0,
                },
                "cost": 0.0042,
            }
        )

        events = parse_docker_agent_events(stdout, {"trace": {"parser": "opencode_json"}})

        model_call = next(event for event in events if event.type == "model_call")
        self.assertEqual(model_call.data["input_tokens"], 7977)
        self.assertEqual(model_call.data["cached_input_tokens"], 12)
        self.assertEqual(model_call.data["output_tokens"], 38)
        self.assertEqual(model_call.data["reasoning_output_tokens"], 35)
        self.assertEqual(model_call.data["cost_usd"], 0.0042)

    def test_parse_goose_complete_top_level_usage(self):
        stdout = json.dumps(
            {
                "type": "complete",
                "total_tokens": 18727,
                "input_tokens": 18396,
                "output_tokens": 331,
            }
        )

        events = parse_docker_agent_events(stdout, {"trace": {"parser": "goose_stream_json"}})

        model_call = next(event for event in events if event.type == "model_call")
        self.assertEqual(model_call.data["input_tokens"], 18396)
        self.assertEqual(model_call.data["output_tokens"], 331)

    def test_parse_aider_text_tokens(self):
        stdout = "Tokens: 622 sent, 113 received. Cost: $0.0031\n"

        events = parse_docker_agent_events(stdout, {"trace": {"parser": "aider_text"}})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].data["input_tokens"], 622)
        self.assertEqual(events[0].data["output_tokens"], 113)
        self.assertEqual(events[0].data["cost_usd"], 0.0031)

    def test_parse_usage_proxy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".harness-usage-proxy.jsonl").write_text(
                json.dumps(
                    {
                        "source": "usage_proxy",
                        "model": "nvidia/test",
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 4,
                            "prompt_tokens_details": {"cached_tokens": 3},
                        },
                        "cost_usd": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            events = parse_proxy_trace_events(
                workspace,
                {"trace": {"proxy": {"trace_path": ".harness-usage-proxy.jsonl"}}},
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].data["input_tokens"], 12)
        self.assertEqual(events[0].data["cached_input_tokens"], 3)
        self.assertEqual(events[0].data["output_tokens"], 4)
        self.assertEqual(events[0].data["cost_usd"], 0)
        self.assertEqual(events[0].data["metadata"]["source"], "usage_proxy")

    def test_parse_usage_proxy_file_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            (root / ".harness-usage-proxy.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "source": "usage_proxy",
                                "model": "nvidia/test",
                                "usage": {"input_tokens": 99, "output_tokens": 1},
                                "request_id": "req-later",
                                "request_started_at": "2026-06-08T00:00:02+00:00",
                                "status_code": 200,
                            }
                        ),
                        json.dumps(
                            {
                                "source": "usage_proxy",
                                "model": "nvidia/test",
                                "usage": {
                                    "input_tokens": 12,
                                    "output_tokens": 4,
                                    "output_tokens_details": {"thinking_tokens": 3},
                                },
                                "request_id": "req-test",
                                "request_started_at": "2026-06-08T00:00:01+00:00",
                                "status_code": 200,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            events = parse_proxy_trace_events(
                workspace,
                {"trace": {"proxy": {"trace_path": "../.harness-usage-proxy.jsonl"}}},
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].data["input_tokens"], 12)
        self.assertEqual(events[0].data["reasoning_output_tokens"], 3)
        self.assertEqual(events[0].data["metadata"]["request_id"], "req-test")
        self.assertEqual(events[0].data["metadata"]["status_code"], 200)
        self.assertEqual(events[1].data["input_tokens"], 99)

    def test_select_trace_prefers_proxy_when_it_has_cost_for_same_call_count(self):
        native = [tool_result_event(name="shell", output="ok"), model_call_event(call_index=0, input_tokens=10)]
        proxy = [model_call_event(call_index=0, input_tokens=10, cost_usd=0.001)]

        events, source = _select_trace_events(native, proxy)

        self.assertEqual(source, "proxy")
        self.assertEqual(len([event for event in events if event.type == "model_call"]), 1)
        self.assertEqual(events[-1].data["cost_usd"], 0.001)

    def test_select_trace_prefers_proxy_non_aggregate_over_native_aggregate(self):
        native = [
            tool_result_event(name="shell", output="ok"),
            model_call_event(
                call_index=0,
                input_tokens=100,
                cost_usd=0.001,
                metadata={"source": "native_total", "aggregate": True},
            ),
        ]
        proxy = [model_call_event(call_index=0, input_tokens=10, metadata={"source": "usage_proxy"})]

        events, source = _select_trace_events(native, proxy)

        model_calls = [event for event in events if event.type == "model_call"]
        self.assertEqual(source, "proxy")
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 10)
        self.assertEqual(events[0].type, "tool_result")


if __name__ == "__main__":
    unittest.main()
