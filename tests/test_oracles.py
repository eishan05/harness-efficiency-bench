import tempfile
import unittest
from pathlib import Path

from harness_efficiency_bench.manifests import OracleSpec
from harness_efficiency_bench.oracles import grade_oracle


class OracleTest(unittest.TestCase):
    def test_file_equals_is_strict_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "answer.txt").write_text("hello benchmark\n", encoding="utf-8")
            result = grade_oracle(
                OracleSpec(type="file_equals", path="answer.txt", text="hello benchmark"),
                workspace,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.message, "file content mismatch")

    def test_file_equals_can_allow_single_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "answer.txt").write_text("hello benchmark\n", encoding="utf-8")
            result = grade_oracle(
                OracleSpec(
                    type="file_equals",
                    path="answer.txt",
                    text="hello benchmark",
                    data={"allow_trailing_newline": True},
                ),
                workspace,
            )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "file matched")

    def test_file_equals_trailing_newline_option_does_not_ignore_extra_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "answer.txt").write_text("hello benchmark\n\n", encoding="utf-8")
            result = grade_oracle(
                OracleSpec(
                    type="file_equals",
                    path="answer.txt",
                    text="hello benchmark",
                    data={"allow_trailing_newline": True},
                ),
                workspace,
            )

        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
