import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from harness_efficiency_bench.cli import main


ROOT = Path(__file__).resolve().parents[1]


def write_task(root: Path, task_id: str, tags: list[str]) -> None:
    task_dir = root / task_id
    task_dir.mkdir()
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    (task_dir / "task.yaml").write_text(
        f"""id: {task_id}
source: local
workspace_setup:
  git_init: true
prompt: |
  Create answer.txt.
oracle:
  type: file_equals
  path: answer.txt
  text: ok
tags:
{tags_yaml}
""",
        encoding="utf-8",
    )


class CliTest(unittest.TestCase):
    def test_tasks_filters_by_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = Path(tmp) / "tasks"
            tasks_dir.mkdir()
            write_task(tasks_dir, "score", ["score-facing", "non-swe"])
            write_task(tasks_dir, "calibration", ["metrics-calibration"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "tasks",
                        "--tasks-dir",
                        str(tasks_dir),
                        "--include-tag",
                        "score-facing",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([item["id"] for item in payload], ["score"])

    def test_run_suite_filters_by_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_dir = root / "tasks"
            tasks_dir.mkdir()
            write_task(tasks_dir, "score", ["score-facing", "non-swe"])
            write_task(tasks_dir, "calibration", ["metrics-calibration"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--run-root",
                        str(root / "runs"),
                        "run-suite",
                        "--tasks-dir",
                        str(tasks_dir),
                        "--harness",
                        str(ROOT / "examples/harnesses/demo.yaml"),
                        "--include-tag",
                        "score-facing",
                        "--delete-workspace",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["attempted"], 1)
        self.assertEqual(payload["results"][0]["task_id"], "score")


if __name__ == "__main__":
    unittest.main()
