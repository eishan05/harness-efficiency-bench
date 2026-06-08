"""Benchmark runner."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .adapters import create_adapter
from .adapters.base import AdapterRunContext
from .isolation import describe_isolation, require_docker_isolation
from .manifests import HarnessManifest, TaskManifest
from .metrics import compute_run_metrics, research_metric_coverage, usage_token_cost
from .oracles import grade_oracle
from .pricing import apply_pricing
from .store import ResultStore
from .tokenization import count_tokens, make_token_payload
from .tracing import TraceEvent, utc_now


class BenchmarkRunner:
    def __init__(self, run_root: str | Path = "runs", *, require_docker: bool = False):
        self.store = ResultStore(run_root)
        self.require_docker = require_docker

    def run_task(
        self,
        task: TaskManifest,
        harness: HarnessManifest,
        *,
        perturbation_id: str | None = None,
        keep_workspace: bool = True,
    ) -> dict[str, Any]:
        run_id = f"{task.id}__{harness.id}__{uuid.uuid4().hex[:10]}"
        if self.require_docker:
            require_docker_isolation(harness)
        self.store.ensure()
        workspace = self.store.work_dir / run_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        self._copy_fixtures(task, workspace)
        self._setup_workspace(task, workspace)
        prompt = self._render_prompt(task, perturbation_id)
        prompt_file = workspace / ".benchmark_prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        adapter = create_adapter(harness)
        started_at = utc_now()
        adapter_result = adapter.run(
            AdapterRunContext(
                run_id=run_id,
                task=task,
                harness=harness,
                workspace=workspace,
                prompt=prompt,
                prompt_file=prompt_file,
                timeout_sec=harness.timeout_sec,
            )
        )
        finished_at = utc_now()

        oracle_result = grade_oracle(task.oracle, workspace)
        events = adapter_result.trace_events + [
            TraceEvent(
                type="grader",
                data={"oracle_result": oracle_result.to_dict(), "adapter_exit_code": adapter_result.exit_code},
            )
        ]
        apply_pricing(events, harness)
        user_prompt_tokens = count_tokens(prompt)
        metrics = compute_run_metrics(events, user_prompt_tokens)
        trace_path = self.store.write_trace(run_id, events)
        artifacts = dict(adapter_result.artifacts)
        artifacts.setdefault("git_diff", self._collect_git_diff(workspace))

        result: dict[str, Any] = {
            "run_id": run_id,
            "task_id": task.id,
            "harness_id": harness.id,
            "adapter": harness.adapter,
            "model_id": adapter_result.metadata.get("model_id") or harness.model,
            "perturbation_id": perturbation_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "success": bool(oracle_result.success and adapter_result.exit_code == 0),
            "adapter_exit_code": adapter_result.exit_code,
            "stdout": adapter_result.stdout,
            "stderr": adapter_result.stderr,
            "artifacts": artifacts,
            "metadata": adapter_result.metadata,
            "oracle_result": oracle_result.to_dict(),
            "metrics": metrics,
            "isolation": describe_isolation(harness),
            "trace_path": str(trace_path),
            "workspace": str(workspace) if keep_workspace else None,
        }
        result_path = self.store.write_result(run_id, result)
        result["result_path"] = str(result_path)
        if not keep_workspace:
            shutil.rmtree(workspace.parent, ignore_errors=True)
        return result

    def _copy_fixtures(self, task: TaskManifest, workspace: Path) -> None:
        if not task.fixtures:
            return
        fixture_path = task.path.parent / task.fixtures
        if not fixture_path.exists():
            raise FileNotFoundError(f"fixtures path does not exist: {fixture_path}")
        if fixture_path.is_dir():
            for item in fixture_path.iterdir():
                destination = workspace / item.name
                if item.is_dir():
                    shutil.copytree(item, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, destination)
        else:
            shutil.copy2(fixture_path, workspace / fixture_path.name)

    def _setup_workspace(self, task: TaskManifest, workspace: Path) -> None:
        setup = task.workspace_setup
        if setup.get("git_init"):
            self._run_setup_command(["git", "init"], workspace)
            self._run_setup_command(["git", "config", "user.email", "benchmark@example.invalid"], workspace)
            self._run_setup_command(["git", "config", "user.name", "Harness Benchmark"], workspace)
            self._run_setup_command(["git", "add", "-A"], workspace)
            self._run_setup_command(["git", "commit", "--allow-empty", "-m", "baseline"], workspace)
        for command in setup.get("commands", []):
            self._run_setup_command(str(command), workspace)

    @staticmethod
    def _run_setup_command(command: str | list[str], workspace: Path) -> None:
        completed = subprocess.run(
            command,
            cwd=workspace,
            shell=isinstance(command, str),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"workspace setup command failed: {command}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

    @staticmethod
    def _collect_git_diff(workspace: Path) -> str:
        if not (workspace / ".git").exists():
            return ""
        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if toplevel.returncode != 0:
            return ""
        try:
            if Path(toplevel.stdout.strip()).resolve() != workspace.resolve():
                return ""
        except OSError:
            return ""
        subprocess.run(
            ["git", "add", "-N", "."],
            cwd=workspace,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            ["git", "reset", "-q", "--", ".benchmark_prompt.txt"],
            cwd=workspace,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "HEAD",
                "--",
                ".",
                ":(exclude).benchmark_prompt.txt",
                ":(exclude).codex_rollout_trace",
                ":(exclude)**/.codex_rollout_trace",
            ],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.stdout if completed.returncode == 0 else ""

    def _render_prompt(self, task: TaskManifest, perturbation_id: str | None) -> str:
        prompt = task.prompt
        perturbation = task.perturbation(perturbation_id)
        if not perturbation or perturbation.tokens <= 0:
            return prompt
        payload = make_token_payload(perturbation.tokens, perturbation.seed)
        if perturbation.placement == "prompt_suffix":
            return f"{prompt}\n\n[Injected context]\n{payload}\n"
        return f"[Injected context]\n{payload}\n\n{prompt}"


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    solved = sum(1 for item in results if item.get("success"))
    total_cost = sum(float(item.get("metrics", {}).get("usage", {}).get("cost_usd", 0.0) or 0.0) for item in results)
    total_token_cost = sum(_result_token_cost(item) for item in results)
    all_dollar_costs_available = bool(results) and all(_result_dollar_cost_available(item) for item in results)
    by_harness: dict[str, dict[str, Any]] = {}
    for item in results:
        harness_id = str(item.get("harness_id"))
        bucket = by_harness.setdefault(
            harness_id,
            {
                "attempted": 0,
                "solved": 0,
                "token_cost": 0,
                "cost_usd": 0.0,
                "runs_with_dollar_cost": 0,
                "metric_values": {
                    "startup_tax": [],
                    "context_growth_rate": [],
                },
            },
        )
        bucket["attempted"] += 1
        bucket["solved"] += 1 if item.get("success") else 0
        bucket["token_cost"] += _result_token_cost(item)
        bucket["cost_usd"] += float(item.get("metrics", {}).get("usage", {}).get("cost_usd", 0.0) or 0.0)
        bucket["runs_with_dollar_cost"] += 1 if _result_dollar_cost_available(item) else 0
        for metric_name in bucket["metric_values"]:
            metric = item.get("metrics", {}).get(metric_name, {})
            if metric.get("status") == "full" and metric.get("value") is not None:
                bucket["metric_values"][metric_name].append(float(metric["value"]))
    for bucket in by_harness.values():
        bucket["solve_rate"] = bucket["solved"] / bucket["attempted"] if bucket["attempted"] else 0.0
        bucket["token_cost_per_solved_task"] = (
            bucket["token_cost"] / bucket["solved"] if bucket["solved"] else None
        )
        bucket["dollar_cost_per_solved_task"] = (
            bucket["cost_usd"] / bucket["solved"]
            if bucket["solved"] and bucket["runs_with_dollar_cost"] == bucket["attempted"]
            else None
        )
        bucket["metrics"] = {
            name: {
                "avg": (sum(values) / len(values)) if values else None,
                "count": len(values),
            }
            for name, values in bucket.pop("metric_values").items()
        }
    return {
        "attempted": total,
        "solved": solved,
        "solve_rate": solved / total if total else 0.0,
        "token_cost": total_token_cost,
        "token_cost_per_solved_task": total_token_cost / solved if solved else None,
        "cost_usd": total_cost,
        "dollar_cost_per_solved_task": (
            total_cost / solved if solved and all_dollar_costs_available else None
        ),
        "by_harness": by_harness,
        "by_perturbation": _summarize_by_perturbation(results),
        "research_metric_coverage": research_metric_coverage(results),
    }


def _result_token_cost(item: dict[str, Any]) -> int:
    usage = item.get("metrics", {}).get("usage", {})
    return usage_token_cost(usage)


def _result_dollar_cost_available(item: dict[str, Any]) -> bool:
    usage = item.get("metrics", {}).get("usage", {})
    return usage_token_cost(usage) > 0 and bool(usage.get("cost_available"))


def _summarize_by_perturbation(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for item in results:
        perturbation_id = str(item.get("perturbation_id") or "base")
        bucket = buckets.setdefault(perturbation_id, {"attempted": 0, "solved": 0})
        bucket["attempted"] += 1
        bucket["solved"] += 1 if item.get("success") else 0
    for bucket in buckets.values():
        bucket["solve_rate"] = bucket["solved"] / bucket["attempted"] if bucket["attempted"] else 0.0
    return buckets
