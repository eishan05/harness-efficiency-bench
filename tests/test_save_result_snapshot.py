import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/save_result_snapshot.py"


def load_snapshot_module():
    spec = importlib.util.spec_from_file_location("save_result_snapshot", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SaveResultSnapshotTest(unittest.TestCase):
    def test_filter_results_to_tasks_dir_keeps_matching_task_ids(self):
        module = load_snapshot_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "wanted"
            task_dir.mkdir(parents=True)
            (task_dir / "task.yaml").write_text("id: wanted\nprompt: do it\n", encoding="utf-8")

            filtered = module._filter_results_to_tasks_dir(
                [
                    {"task_id": "wanted"},
                    {"task_id": "other"},
                ],
                root / "tasks",
            )

        self.assertEqual(filtered, [{"task_id": "wanted"}])

    def test_apply_swe_report_overrides_oracle_labels(self):
        module = load_snapshot_module()
        results = [
            {
                "task_id": "django__django-11905",
                "adapter_exit_code": 0,
                "success": False,
                "oracle_result": {"success": False, "score": 0.0, "message": "old"},
                "metadata": {},
            },
            {
                "task_id": "sympy__sympy-14308",
                "adapter_exit_code": 0,
                "success": True,
                "oracle_result": {"success": True, "score": 1.0, "message": "old"},
                "metadata": {},
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "resolved_ids": ["django__django-11905"],
                        "unresolved_ids": [],
                        "empty_patch_ids": ["sympy__sympy-14308"],
                    }
                ),
                encoding="utf-8",
            )
            predictions = root / "predictions.jsonl"
            predictions.write_text(
                "\n".join(
                    [
                        json.dumps({"instance_id": "django__django-11905", "model_patch": "diff"}),
                        json.dumps({"instance_id": "sympy__sympy-14308", "model_patch": ""}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            updated = module._apply_swe_report_overrides(results, [str(report)], [str(predictions)])

        self.assertTrue(updated[0]["success"])
        self.assertEqual(updated[0]["oracle_result"]["message"], "swe-bench instance resolved")
        self.assertFalse(updated[1]["success"])
        self.assertEqual(updated[1]["oracle_result"]["message"], "swe-bench instance unresolved (empty patch)")
        self.assertIn("swe_bench_regraded_from_report", updated[0]["metadata"])


if __name__ == "__main__":
    unittest.main()
