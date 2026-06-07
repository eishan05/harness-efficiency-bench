import unittest
from pathlib import Path

from harness_efficiency_bench.manifests import HarnessManifest, TaskManifest


ROOT = Path(__file__).resolve().parents[1]


class ManifestTest(unittest.TestCase):
    def test_load_task_manifest(self):
        task = TaskManifest.load(ROOT / "examples/tasks/toy-write-file/task.yaml")
        self.assertEqual(task.id, "toy-write-file")
        self.assertEqual(task.oracle.type, "file_equals")
        self.assertTrue(task.workspace_setup["git_init"])
        self.assertEqual(task.perturbation("20k").tokens, 20000)

    def test_load_harness_manifest(self):
        harness = HarnessManifest.load(ROOT / "examples/harnesses/demo.yaml")
        self.assertEqual(harness.id, "demo")
        self.assertEqual(harness.adapter, "demo")


if __name__ == "__main__":
    unittest.main()
