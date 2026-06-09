import tempfile
import unittest
from pathlib import Path

from path_safety import safe_join


class PathSafetyTest(unittest.TestCase):
    def test_safe_path_is_joined_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(safe_join(root, "reports/2026.txt"), root / "reports" / "2026.txt")

    def test_normalized_internal_parent_segment_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(safe_join(root, "reports/../summary.txt"), root / "summary.txt")

    def test_absolute_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                safe_join(tmp, "/etc/passwd")

    def test_traversal_that_escapes_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                safe_join(tmp, "nested/../../secret.txt")


if __name__ == "__main__":
    unittest.main()
