import json
import unittest

from harness_efficiency_bench.adapters.claude_code import ClaudeCodeAdapter


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


if __name__ == "__main__":
    unittest.main()
