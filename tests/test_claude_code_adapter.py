import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.claude_code import ClaudeCodeAdapter, _with_openrouter_environment
from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


class ClaudeCodeAdapterTest(unittest.TestCase):
    def test_parse_assistant_usage_tool_result_and_final_cost(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 10,
                                "cache_creation_input_tokens": 4,
                                "cache_read_input_tokens": 0,
                                "output_tokens": 2,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_1",
                                    "content": [{"type": "text", "text": "pytest failed"}],
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 20,
                                "cache_read_input_tokens": 5,
                                "output_tokens": 3,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "total_cost_usd": 0.0123,
                        "usage": {
                            "input_tokens": 30,
                            "cache_creation_input_tokens": 4,
                            "cache_read_input_tokens": 5,
                            "output_tokens": 5,
                        },
                    }
                ),
            ]
        )

        events = ClaudeCodeAdapter._parse_events(stdout)
        model_calls = [event for event in events if event.type == "model_call"]
        tool_results = [event for event in events if event.type == "tool_result"]

        self.assertEqual(len(model_calls), 2)
        self.assertEqual(model_calls[0].data["input_tokens"], 14)
        self.assertEqual(model_calls[1].data["input_tokens"], 25)
        self.assertEqual(model_calls[1].data["cached_input_tokens"], 5)
        self.assertEqual(model_calls[1].data["cost_usd"], 0.0123)
        self.assertEqual(tool_results[0].data["name"], "toolu_1")
        self.assertEqual(tool_results[0].data["output"], "pytest failed")

    def test_failed_auth_result_does_not_emit_zero_usage_model_call(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "apiKeySource": "none"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "error": "authentication_failed",
                        "message": {"content": [{"type": "text", "text": "access denied"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "is_error": True,
                        "api_error_status": 403,
                        "total_cost_usd": 0,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    }
                ),
            ]
        )

        events = ClaudeCodeAdapter._parse_events(stdout)

        self.assertFalse([event for event in events if event.type == "model_call"])
        self.assertTrue(
            any(
                event.type == "claude_event"
                and event.data["raw"].get("type") == "result"
                and event.data["raw"].get("api_error_status") == 403
                for event in events
            )
        )

    def test_result_usage_fallback_when_assistant_usage_is_absent(self):
        stdout = json.dumps(
            {
                "type": "result",
                "total_cost_usd": "0.001",
                "usage": {"input_tokens": 7, "output_tokens": 1},
            }
        )

        events = ClaudeCodeAdapter._parse_events(stdout)
        model_calls = [event for event in events if event.type == "model_call"]

        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 7)
        self.assertEqual(model_calls[0].data["cost_usd"], 0.001)

    def test_openrouter_model_usage_fallback_when_result_usage_is_zero(self):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 0,
                                "cache_creation_input_tokens": None,
                                "cache_read_input_tokens": None,
                                "output_tokens": 0,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                        "modelUsage": {
                            "nvidia/nemotron-3-ultra-550b-a55b:free": {
                                "inputTokens": 10,
                                "cacheReadInputTokens": 2,
                                "cacheCreationInputTokens": 3,
                                "outputTokens": 4,
                                "reasoningTokens": 5,
                                "costUSD": 0.0007,
                            }
                        },
                    }
                ),
            ]
        )

        events = ClaudeCodeAdapter._parse_events(stdout)
        model_calls = [event for event in events if event.type == "model_call"]

        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 15)
        self.assertEqual(model_calls[0].data["cached_input_tokens"], 2)
        self.assertEqual(model_calls[0].data["output_tokens"], 4)
        self.assertEqual(model_calls[0].data["reasoning_output_tokens"], 5)
        self.assertEqual(model_calls[0].data["cost_usd"], 0.0007)
        self.assertEqual(model_calls[0].data["metadata"]["source"], "claude_openrouter_model_usage")
        self.assertTrue(model_calls[0].data["metadata"]["aggregate"])

    def test_openrouter_model_usage_is_preferred_over_result_usage(self):
        stdout = json.dumps(
            {
                "type": "result",
                "usage": {"input_tokens": 10, "output_tokens": 2},
                "modelUsage": {
                    "nvidia/nemotron-3-ultra-550b-a55b:free": {
                        "inputTokens": 20,
                        "outputTokens": 4,
                        "costUSD": 0.001,
                    }
                },
            }
        )

        events = ClaudeCodeAdapter._parse_events(stdout)
        model_calls = [event for event in events if event.type == "model_call"]

        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 20)
        self.assertEqual(model_calls[0].data["output_tokens"], 4)
        self.assertEqual(model_calls[0].data["cost_usd"], 0.001)
        self.assertEqual(model_calls[0].data["metadata"]["source"], "claude_openrouter_model_usage")

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-test-openrouter", "OPENROUTER_MODEL": "nvidia/test-model:free"},
    )
    def test_openrouter_environment_maps_to_anthropic_gateway_vars(self):
        harness = HarnessManifest(
            id="claude-code-openrouter",
            adapter="claude_code",
            path=Path("harness.yaml"),
            model="${OPENROUTER_MODEL}",
            config={"auth_mode": "openrouter"},
        )
        task = TaskManifest(id="task", prompt="prompt", path=Path("task.yaml"))
        context = AdapterRunContext(
            run_id="run",
            task=task,
            harness=harness,
            workspace=Path("."),
            prompt="prompt",
            prompt_file=Path(".benchmark_prompt.txt"),
            timeout_sec=1,
        )

        active_context = _with_openrouter_environment(context)

        self.assertEqual(active_context.harness.model, "nvidia/test-model:free")
        self.assertEqual(active_context.harness.env["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api")
        self.assertEqual(active_context.harness.env["ANTHROPIC_AUTH_TOKEN"], "sk-test-openrouter")
        self.assertEqual(active_context.harness.env["ANTHROPIC_API_KEY"], "")
        self.assertEqual(active_context.harness.env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "nvidia/test-model:free")

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-test-openrouter", "OPENROUTER_MODEL": "nvidia/test-model:free"},
    )
    def test_run_prefers_proxy_usage_over_openrouter_aggregate_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / ".harness-usage-proxy.jsonl"

            class FakeProxy:
                def __init__(self):
                    self.config = SimpleNamespace(trace_path=trace_path)
                    self.local_base_url = "http://127.0.0.1:1234/api"
                    self.docker_base_url = "http://host.docker.internal:1234/api"
                    self.started = False
                    self.stopped = False

                def start(self):
                    self.started = True

                def stop(self):
                    self.stopped = True

                def env(self, *, docker):
                    self.docker = docker
                    return {
                        "ANTHROPIC_BASE_URL": self.docker_base_url,
                        "ANTHROPIC_AUTH_TOKEN": "sk-test-openrouter",
                    }

            fake_proxy = FakeProxy()
            harness = HarnessManifest(
                id="claude-code-docker-openrouter",
                adapter="claude_code",
                path=root / "harness.yaml",
                model="${OPENROUTER_MODEL}",
                config={
                    "auth_mode": "openrouter",
                    "backend": "docker",
                    "required_env": ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"],
                    "trace": {"proxy": {"enabled": True, "trace_path": ".harness-usage-proxy.jsonl"}},
                },
            )
            task = TaskManifest(id="task", prompt="prompt", path=root / "task.yaml")
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=root,
                prompt="prompt",
                prompt_file=root / ".benchmark_prompt.txt",
                timeout_sec=1,
            )

            def fake_run_command(command, active_context, stdin=None):
                self.assertTrue(active_context.harness.config["docker_add_host_gateway"])
                self.assertEqual(active_context.harness.env["ANTHROPIC_BASE_URL"], fake_proxy.docker_base_url)
                self.assertEqual(active_context.harness.env["ANTHROPIC_AUTH_TOKEN"], "sk-test-openrouter")
                self.assertIsNone(stdin)
                trace_path.write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "source": "usage_proxy",
                                    "model": "nvidia/test-model:free",
                                    "request_id": "hidden-preflight",
                                    "usage": {"input_tokens": 3, "output_tokens": 1},
                                    "status_code": 200,
                                }
                            ),
                            json.dumps(
                                {
                                    "source": "usage_proxy",
                                    "model": "nvidia/test-model:free",
                                    "request_id": "visible-message",
                                    "usage": {"input_tokens": 9, "output_tokens": 2},
                                    "status_code": 200,
                                }
                            ),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                stdout = "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "id": "visible-message",
                                    "usage": {"input_tokens": 0, "output_tokens": 0},
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "result",
                                "usage": {"input_tokens": 0, "output_tokens": 0},
                                "modelUsage": {
                                    "nvidia/test-model:free": {
                                        "inputTokens": 99,
                                        "outputTokens": 4,
                                        "costUSD": 0.001,
                                    }
                                },
                            }
                        ),
                    ]
                )
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            with patch(
                "harness_efficiency_bench.adapters.claude_code.proxy_from_config",
                return_value=fake_proxy,
            ), patch("harness_efficiency_bench.adapters.claude_code.run_command", side_effect=fake_run_command):
                result = ClaudeCodeAdapter(harness).run(context)

        model_calls = [event for event in result.trace_events if event.type == "model_call"]
        self.assertTrue(fake_proxy.started)
        self.assertTrue(fake_proxy.stopped)
        self.assertTrue(fake_proxy.docker)
        self.assertEqual(len(model_calls), 2)
        self.assertEqual(model_calls[0].data["input_tokens"], 3)
        self.assertTrue(model_calls[0].data["metadata"]["preflight"])
        self.assertEqual(model_calls[1].data["input_tokens"], 9)
        self.assertEqual(model_calls[1].data["output_tokens"], 2)
        self.assertEqual(model_calls[0].data["metadata"]["source"], "usage_proxy")
        self.assertNotIn("aggregate", model_calls[1].data["metadata"])
        self.assertEqual(result.metadata["proxy_trace"], "parsed")
        self.assertEqual(result.metadata["selected_trace_source"], "proxy")

    def test_stdin_prompt_config_passes_prompt_to_command_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = HarnessManifest(
                id="claude-code-docker-openrouter",
                adapter="claude_code",
                path=root / "harness.yaml",
                command=["claude", "-p"],
                model="test-model",
                config={"stdin_prompt": True},
            )
            task = TaskManifest(id="task", prompt="prompt from task", path=root / "task.yaml")
            context = AdapterRunContext(
                run_id="run",
                task=task,
                harness=harness,
                workspace=root,
                prompt="prompt from task",
                prompt_file=root / ".benchmark_prompt.txt",
                timeout_sec=1,
            )

            def fake_run_command(command, active_context, stdin=None):
                self.assertEqual(command, ["claude", "-p"])
                self.assertEqual(stdin, "prompt from task")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("harness_efficiency_bench.adapters.claude_code.run_command", side_effect=fake_run_command):
                result = ClaudeCodeAdapter(harness).run(context)

        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
