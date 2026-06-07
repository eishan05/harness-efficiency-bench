import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from harness_efficiency_bench.adapters.base import AdapterRunContext
from harness_efficiency_bench.adapters.codex import CodexAdapter
from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


class CodexAdapterTest(unittest.TestCase):
    def test_parse_command_execution_as_tool_result(self):
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "pytest",
                            "aggregated_output": "failed test output",
                            "exit_code": 1,
                            "status": "failed",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 2,
                            "output_tokens": 3,
                            "reasoning_output_tokens": 1,
                        },
                    }
                ),
            ]
        )

        events = CodexAdapter._parse_events(stdout)
        self.assertEqual(events[0].type, "tool_result")
        self.assertEqual(events[0].data["output"], "failed test output")
        self.assertEqual(events[-1].type, "model_call")

    def test_parse_rollout_trace_model_calls(self):
        state = {
            "inference_calls": {
                "second": {
                    "inference_call_id": "second",
                    "codex_turn_id": "turn-1",
                    "execution": {"started_seq": 20},
                    "model": "gpt-5.5",
                    "provider_name": "OpenAI",
                    "usage": {
                        "input_tokens": 15,
                        "cached_input_tokens": 5,
                        "output_tokens": 2,
                        "reasoning_output_tokens": 1,
                    },
                },
                "first": {
                    "inference_call_id": "first",
                    "codex_turn_id": "turn-1",
                    "execution": {"started_seq": 10},
                    "model": "gpt-5.5",
                    "provider_name": "OpenAI",
                    "usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                    },
                },
            }
        }

        events = CodexAdapter._rollout_model_calls_from_state(state)

        self.assertEqual([event.data["call_index"] for event in events], [0, 1])
        self.assertEqual([event.data["input_tokens"] for event in events], [10, 15])
        self.assertEqual(events[0].data["metadata"]["source"], "codex_rollout_trace")

    def test_parse_raw_rollout_trace_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "manifest.json").write_text("{}", encoding="utf-8")
            (bundle / "payloads").mkdir()
            (bundle / "payloads/2.json").write_text(
                json.dumps(
                    {
                        "response_id": "resp_1",
                        "token_usage": {
                            "input_tokens": 42,
                            "cached_input_tokens": 12,
                            "output_tokens": 7,
                            "reasoning_output_tokens": 3,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (bundle / "trace.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "seq": 10,
                                "payload": {
                                    "type": "inference_started",
                                    "inference_call_id": "call-1",
                                    "codex_turn_id": "turn-1",
                                    "model": "gpt-5.5",
                                    "provider_name": "OpenAI",
                                    "request_payload": {"path": "payloads/1.json"},
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "seq": 11,
                                "payload": {
                                    "type": "inference_completed",
                                    "inference_call_id": "call-1",
                                    "response_payload": {"path": "payloads/2.json"},
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            events = CodexAdapter._rollout_model_calls_from_bundle(bundle)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "model_call")
        self.assertEqual(events[0].data["input_tokens"], 42)
        self.assertEqual(events[0].data["cached_input_tokens"], 12)
        self.assertEqual(events[0].data["metadata"]["inference_call_id"], "call-1")

    def test_run_uses_rollout_usage_and_removes_raw_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            prompt_file = workspace / ".benchmark_prompt.txt"
            prompt_file.write_text("prompt", encoding="utf-8")
            fake_codex = root / "fake_codex.py"
            fake_codex.write_text(
                textwrap.dedent(
                    """
                    import json
                    import os
                    import pathlib
                    import sys

                    sys.stdin.read()
                    trace_root = pathlib.Path(os.environ["CODEX_ROLLOUT_TRACE_ROOT"])
                    bundle = trace_root / "trace-test"
                    (bundle / "payloads").mkdir(parents=True)
                    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
                    (bundle / "payloads/1.json").write_text(
                        json.dumps(
                            {
                                "token_usage": {
                                    "input_tokens": 11,
                                    "cached_input_tokens": 3,
                                    "output_tokens": 2,
                                    "reasoning_output_tokens": 1,
                                }
                            }
                        ),
                        encoding="utf-8",
                    )
                    (bundle / "trace.jsonl").write_text(
                        "\\n".join(
                            [
                                json.dumps(
                                    {
                                        "seq": 4,
                                        "payload": {
                                            "type": "inference_started",
                                            "inference_call_id": "call-1",
                                            "codex_turn_id": "turn-1",
                                            "model": "gpt-test",
                                            "provider_name": "OpenAI",
                                        },
                                    }
                                ),
                                json.dumps(
                                    {
                                        "seq": 5,
                                        "payload": {
                                            "type": "inference_completed",
                                            "inference_call_id": "call-1",
                                            "response_payload": {"path": "payloads/1.json"},
                                        },
                                    }
                                ),
                            ]
                        ),
                        encoding="utf-8",
                    )
                    print(
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "usage": {
                                    "input_tokens": 999,
                                    "cached_input_tokens": 999,
                                    "output_tokens": 999,
                                    "reasoning_output_tokens": 999,
                                },
                            }
                        )
                    )
                    """
                ).strip(),
                encoding="utf-8",
            )
            harness = HarnessManifest(
                id="codex-test",
                adapter="codex",
                path=root / "harness.yaml",
                command=["python3", str(fake_codex)],
                model="gpt-test",
                config={"codex_rollout_trace": True},
            )
            task = TaskManifest(id="task", prompt="prompt", path=root / "task.yaml")

            result = CodexAdapter(harness).run(
                AdapterRunContext(
                    run_id="run-1",
                    task=task,
                    harness=harness,
                    workspace=workspace,
                    prompt="prompt",
                    prompt_file=prompt_file,
                    timeout_sec=30,
                )
            )

        model_calls = [event for event in result.trace_events if event.type == "model_call"]
        self.assertEqual(result.metadata["codex_rollout_trace"], "parsed")
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(model_calls[0].data["input_tokens"], 11)
        self.assertFalse((workspace / ".codex_rollout_trace").exists())


if __name__ == "__main__":
    unittest.main()
