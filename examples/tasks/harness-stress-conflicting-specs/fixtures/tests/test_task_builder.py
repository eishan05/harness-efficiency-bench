import json
import unittest
from pathlib import Path

from task_builder import build_task_card


ROOT = Path(__file__).resolve().parents[1]


class TaskBuilderTest(unittest.TestCase):
    def test_uses_current_spec_and_returns_json(self):
        card = json.loads(build_task_card(ROOT / "specs"))

        self.assertEqual(
            card,
            {
                "title": "Incident cleanup",
                "owner": "platform",
                "priority": "high",
                "runbook": "current-runbook.md",
            },
        )

    def test_deprecated_spec_is_ignored(self):
        card = json.loads(build_task_card(ROOT / "specs"))

        self.assertNotIn("Deprecated", card["title"])
        self.assertNotEqual(card["owner"], "data")


if __name__ == "__main__":
    unittest.main()
