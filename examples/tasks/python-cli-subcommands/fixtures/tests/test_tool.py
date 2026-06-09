import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_tool(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "tool.py"), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class ToolTest(unittest.TestCase):
    def test_requires_subcommand(self):
        completed = run_tool()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("usage:", completed.stderr)

    def test_echo_upper(self):
        completed = run_tool("echo", "--upper", "hello")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "HELLO\n")

    def test_sum_is_numeric(self):
        completed = run_tool("sum", "2", "3", "10")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "15\n")


if __name__ == "__main__":
    unittest.main()
