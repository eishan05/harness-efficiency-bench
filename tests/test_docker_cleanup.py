import subprocess
import unittest
from unittest.mock import patch

from harness_efficiency_bench.docker_cleanup import (
    DockerCleanupPlan,
    execute_docker_cleanup,
    plan_docker_cleanup,
)


class DockerCleanupTest(unittest.TestCase):
    def test_plan_targets_benchmark_resources(self):
        def fake_run(command, *, check=True):
            if command[:3] == ["docker", "ps", "-aq"]:
                return subprocess.CompletedProcess(command, 0, "container1\n", "")
            if command[:2] == ["docker", "images"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    '{"Repository":"harness-bench/codex-cli","Tag":"0.137.0","ID":"abc"}\n'
                    '{"Repository":"other/image","Tag":"latest","ID":"def"}\n',
                    "",
                )
            raise AssertionError(command)

        with patch("harness_efficiency_bench.docker_cleanup._run", side_effect=fake_run):
            plan = plan_docker_cleanup(include_build_cache=True)

        self.assertEqual(plan.containers, ["container1"])
        self.assertEqual(plan.images, ["harness-bench/codex-cli:0.137.0"])
        self.assertTrue(plan.prune_build_cache)

    def test_dry_run_does_not_remove(self):
        plan = DockerCleanupPlan(containers=["container1"], images=["image1"], prune_build_cache=True)
        with patch("harness_efficiency_bench.docker_cleanup._run") as run:
            result = execute_docker_cleanup(plan, dry_run=True)
        run.assert_not_called()
        self.assertTrue(result["dry_run"])

    def test_force_removes_requested_resources(self):
        plan = DockerCleanupPlan(containers=["container1"], images=["image1"], prune_build_cache=True)
        with patch("harness_efficiency_bench.docker_cleanup._run") as run:
            execute_docker_cleanup(plan, dry_run=False)
        run.assert_any_call(["docker", "rm", "-f", "container1"])
        run.assert_any_call(["docker", "rmi", "image1"])
        run.assert_any_call(["docker", "builder", "prune", "-f"])


if __name__ == "__main__":
    unittest.main()
