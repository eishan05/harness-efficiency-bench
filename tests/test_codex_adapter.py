import json
import unittest

from harness_efficiency_bench.adapters.codex import CodexAdapter


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


if __name__ == "__main__":
    unittest.main()
