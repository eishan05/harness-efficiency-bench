#!/usr/bin/env python3
"""Save a compact benchmark result snapshot from an existing run root."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from harness_efficiency_bench.manifests import HarnessManifest  # noqa: E402
from harness_efficiency_bench.manifests import TaskManifest  # noqa: E402
from harness_efficiency_bench.metrics import compute_run_metrics  # noqa: E402
from harness_efficiency_bench.runner import summarize_results  # noqa: E402
from harness_efficiency_bench.store import ResultStore  # noqa: E402
from harness_efficiency_bench.tokenization import count_tokens, make_token_payload  # noqa: E402
from harness_efficiency_bench.tracing import TraceEvent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--harness", required=True, help="Harness manifest path.")
    parser.add_argument("--model", help="Resolved model id to record.")
    parser.add_argument("--suite", default="examples-non-swe-full")
    parser.add_argument("--tasks-dir", default="examples/tasks")
    parser.add_argument(
        "--filter-to-tasks-dir",
        action="store_true",
        help="Only include result files whose task_id appears under --tasks-dir.",
    )
    parser.add_argument("--perturbation-mode", default="all-perturbations")
    parser.add_argument("--oracle-mode", default="task manifests")
    parser.add_argument("--execution", help="Human-readable execution description.")
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument(
        "--swe-report",
        action="append",
        default=[],
        help="SWE-bench evaluator JSON report used to override SWE oracle labels.",
    )
    parser.add_argument(
        "--swe-predictions",
        action="append",
        default=[],
        help="SWE-bench predictions JSONL paired with --swe-report; marks submitted empty/no-op patches.",
    )
    args = parser.parse_args()

    run_root = Path(args.run_root)
    harness = HarnessManifest.load(args.harness)
    results = sorted(
        ResultStore(run_root).iter_results(),
        key=lambda item: (str(item.get("task_id")), str(item.get("perturbation_id") or "base")),
    )
    if not results:
        parser.error(f"no result files found under {run_root}")
    tasks_dir = Path(args.tasks_dir)
    if args.filter_to_tasks_dir:
        results = _filter_results_to_tasks_dir(results, tasks_dir)
        if not results:
            parser.error(f"no result files under {run_root} match tasks from {tasks_dir}")
    results = _recompute_metrics(results, run_root, tasks_dir)
    results = _apply_swe_report_overrides(results, args.swe_report, args.swe_predictions)

    summary = summarize_results(results)
    harness_bucket = summary["by_harness"].get(harness.id)
    if harness_bucket is None:
        parser.error(f"no results found for harness id {harness.id!r}")

    payload = {
        "schema_version": 1,
        "artifact_type": "benchmark_result_snapshot",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "benchmark": {
            "suite": args.suite,
            "tasks_dir": args.tasks_dir,
            "attempted_runs": len(results),
            "run_started_at": min(str(item.get("started_at", "")) for item in results),
            "run_finished_at": max(str(item.get("finished_at", "")) for item in results),
            "oracle_mode": args.oracle_mode,
            "perturbation_mode": args.perturbation_mode,
        },
        "harness": {
            "id": harness.id,
            "base_manifest": args.harness,
            "adapter": harness.adapter,
            "model": args.model or harness.model,
            "execution": args.execution or f"Docker-isolated {harness.id}",
            "docker_image": harness.config.get("docker_image"),
            "timeout_sec": harness.timeout_sec,
        },
        "commands": args.command or None,
        "summary": _snapshot_summary(summary, harness_bucket, results),
        "known_failures": _known_failures(results),
        "per_run": [_per_run(item) for item in results],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


def _recompute_metrics(
    results: list[dict[str, Any]],
    run_root: Path,
    tasks_dir: Path,
) -> list[dict[str, Any]]:
    tasks = _load_tasks(tasks_dir)
    if not tasks:
        return results
    recomputed = []
    for item in results:
        task = tasks.get(str(item.get("task_id")))
        trace_path = _resolve_trace_path(item.get("trace_path"), run_root)
        if task is None or trace_path is None or not trace_path.exists():
            recomputed.append(item)
            continue
        prompt = _render_prompt(task, item.get("perturbation_id"))
        user_prompt_tokens = count_tokens(prompt)
        next_item = dict(item)
        metadata = dict(next_item.get("metadata") or {})
        metadata["user_prompt_tokens"] = user_prompt_tokens
        metadata["metrics_recomputed_from_trace"] = True
        next_item["metadata"] = metadata
        next_item["metrics"] = compute_run_metrics(_read_trace(trace_path), user_prompt_tokens)
        recomputed.append(next_item)
    return recomputed


def _apply_swe_report_overrides(
    results: list[dict[str, Any]],
    report_paths: list[str],
    prediction_paths: list[str],
) -> list[dict[str, Any]]:
    if not report_paths:
        return results
    outcomes = _load_swe_outcomes([Path(path) for path in report_paths], [Path(path) for path in prediction_paths])
    if not outcomes:
        return results

    updated = []
    for item in results:
        task_id = str(item.get("task_id") or "")
        outcome = outcomes.get(task_id)
        if outcome is None:
            updated.append(item)
            continue
        next_item = dict(item)
        oracle_result = dict(next_item.get("oracle_result") or {})
        oracle_result.update(
            {
                "success": outcome["success"],
                "score": 1.0 if outcome["success"] else 0.0,
                "message": outcome["message"],
            }
        )
        details = dict(oracle_result.get("details") or {})
        details["swe_bench_regrade"] = {
            "report_path": outcome["report_path"],
            "outcome": outcome["outcome"],
        }
        oracle_result["details"] = details
        next_item["oracle_result"] = oracle_result
        next_item["success"] = bool(outcome["success"] and next_item.get("adapter_exit_code") == 0)
        metadata = dict(next_item.get("metadata") or {})
        metadata["swe_bench_regraded_from_report"] = outcome["report_path"]
        next_item["metadata"] = metadata
        updated.append(next_item)
    return updated


def _load_swe_outcomes(report_paths: list[Path], prediction_paths: list[Path]) -> dict[str, dict[str, Any]]:
    submitted_ids = _load_prediction_ids(prediction_paths)
    outcomes: dict[str, dict[str, Any]] = {}
    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        resolved = set(_string_list(report.get("resolved_ids")))
        unresolved = set(_string_list(report.get("unresolved_ids")))
        error = set(_string_list(report.get("error_ids")))
        empty_patch = set(_string_list(report.get("empty_patch_ids")))
        incomplete = set(_string_list(report.get("incomplete_ids")))
        all_ids = set(_string_list(report.get("submitted_ids"))) or set(submitted_ids)
        all_ids.update(resolved)
        all_ids.update(unresolved)
        all_ids.update(error)
        all_ids.update(empty_patch)
        all_ids.update(incomplete)
        for instance_id in sorted(all_ids):
            if instance_id in resolved:
                outcome = "resolved"
                success = True
                message = "swe-bench instance resolved"
            elif instance_id in error:
                outcome = "error"
                success = False
                message = "swe-bench evaluation error"
            elif instance_id in empty_patch:
                outcome = "empty_patch"
                success = False
                message = "swe-bench instance unresolved (empty patch)"
            elif instance_id in incomplete:
                outcome = "incomplete"
                success = False
                message = "swe-bench evaluation incomplete"
            else:
                outcome = "unresolved"
                success = False
                message = "swe-bench instance unresolved"
            outcomes[instance_id] = {
                "success": success,
                "message": message,
                "outcome": outcome,
                "report_path": str(report_path),
            }
    return outcomes


def _load_prediction_ids(paths: list[Path]) -> set[str]:
    ids: set[str] = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            instance_id = payload.get("instance_id")
            if instance_id is not None:
                ids.add(str(instance_id))
    return ids


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _load_tasks(tasks_dir: Path) -> dict[str, TaskManifest]:
    paths = _task_manifest_paths(tasks_dir)
    tasks: dict[str, TaskManifest] = {}
    for path in paths:
        try:
            task = TaskManifest.load(path)
        except Exception:
            continue
        tasks[task.id] = task
    return tasks


def _filter_results_to_tasks_dir(results: list[dict[str, Any]], tasks_dir: Path) -> list[dict[str, Any]]:
    task_ids = set(_load_tasks(tasks_dir))
    if not task_ids:
        return results
    return [item for item in results if str(item.get("task_id")) in task_ids]


def _task_manifest_paths(tasks_dir: Path) -> list[Path]:
    if tasks_dir.is_file():
        return [tasks_dir]
    return sorted({*tasks_dir.rglob("task.yaml"), *tasks_dir.glob("*.yaml"), *tasks_dir.glob("*.json")})


def _resolve_trace_path(raw_path: Any, run_root: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute() or path.exists():
        return path
    return run_root / path


def _read_trace(path: Path) -> list[TraceEvent]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(TraceEvent.from_dict(json.loads(line)))
    return events


def _render_prompt(task: TaskManifest, perturbation_id: Any) -> str:
    prompt = task.prompt
    perturbation = task.perturbation(str(perturbation_id)) if perturbation_id else None
    if not perturbation or perturbation.tokens <= 0:
        return prompt
    payload = make_token_payload(perturbation.tokens, perturbation.seed)
    if perturbation.placement == "prompt_suffix":
        return f"{prompt}\n\n[Injected context]\n{payload}\n"
    return f"[Injected context]\n{payload}\n\n{prompt}"


def _snapshot_summary(
    summary: dict[str, Any],
    harness_bucket: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    coverage = summary["research_metric_coverage"]
    oracle_solved = sum(1 for item in results if item.get("oracle_result", {}).get("success"))
    return {
        "attempted": summary["attempted"],
        "solved": summary["solved"],
        "solve_rate": summary["solve_rate"],
        "oracle_solved": oracle_solved,
        "oracle_solve_rate": oracle_solved / len(results) if results else 0.0,
        "metrics": {
            "startup_tax": {
                "research_metric": "A",
                "status": coverage["startup_tax"]["status"],
                "unit": "first-call input tokens",
                "avg": harness_bucket["metrics"]["startup_tax"]["avg"],
                "runs_full": coverage["startup_tax"]["runs_full"],
                "runs_partial": coverage["startup_tax"]["runs_partial"],
                "runs_unsupported": coverage["startup_tax"]["runs_unsupported"],
            },
            "context_growth_rate": {
                "research_metric": "B",
                "status": coverage["context_growth_rate"]["status"],
                "unit": "input tokens per model call",
                "avg": harness_bucket["metrics"]["context_growth_rate"]["avg"],
                "runs_full": coverage["context_growth_rate"]["runs_full"],
                "runs_unsupported": coverage["context_growth_rate"]["runs_unsupported"],
            },
            "token_solve_efficiency": {
                "research_metric": "C",
                "status": coverage["solve_efficiency"]["status"],
                "unit": "tokens per solved task",
                "total_token_cost": summary["token_cost"],
                "token_cost_per_solved_task": summary["token_cost_per_solved_task"],
                "runs_with_token_cost": coverage["solve_efficiency"]["runs_with_token_cost"],
                "runs_without_token_cost": (
                    coverage["solve_efficiency"]["runs_total"]
                    - coverage["solve_efficiency"]["runs_with_token_cost"]
                ),
            },
        },
        "pricing_estimate": {
            "source": _pricing_source(summary, harness_bucket),
            "cost_usd_total_for_usage_runs": summary["cost_usd"],
            "runs_with_dollar_cost": harness_bucket["runs_with_dollar_cost"],
        },
        "by_perturbation": summary["by_perturbation"],
    }


def _pricing_source(summary: dict[str, Any], harness_bucket: dict[str, Any]) -> str:
    if int(harness_bucket.get("runs_with_dollar_cost", 0) or 0) > 0:
        if float(summary.get("cost_usd", 0.0) or 0.0) > 0:
            return "Provider/proxy-reported cost_usd from trace events; manifest pricing is empty."
        return "Provider/proxy reported zero cost_usd for usage-bearing runs; manifest pricing is empty."
    if float(summary.get("cost_usd", 0.0) or 0.0) > 0:
        return "Provider/proxy-reported cost_usd from trace events; manifest pricing is empty."
    return "No manifest pricing configured; dollars remain zero unless the provider/proxy reports cost_usd."


def _known_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for item in results:
        if item.get("success"):
            continue
        metrics = item.get("metrics", {})
        usage = metrics.get("usage", {})
        oracle = item.get("oracle_result", {})
        reason = oracle.get("message")
        if oracle.get("success") and item.get("adapter_exit_code") != 0:
            reason = "oracle passed but adapter returned nonzero"
        failures.append(
            {
                "task_id": item.get("task_id"),
                "perturbation_id": item.get("perturbation_id") or "base",
                "adapter_exit_code": item.get("adapter_exit_code"),
                "oracle_message": oracle.get("message"),
                "oracle_details": oracle.get("details"),
                "reason": reason,
                "token_cost": int(usage.get("token_cost", 0) or 0),
                "metric_impact": (
                    "A/B/C token metrics are available for this run unless the per_run metric status says otherwise."
                ),
            }
        )
    return failures


def _per_run(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item.get("metrics", {})
    usage = metrics.get("usage", {})
    oracle = item.get("oracle_result", {})
    return {
        "task_id": item.get("task_id"),
        "perturbation_id": item.get("perturbation_id") or "base",
        "success": bool(item.get("success")),
        "adapter_exit_code": item.get("adapter_exit_code"),
        "oracle_success": bool(oracle.get("success")),
        "oracle_message": oracle.get("message"),
        "startup_tax": metrics.get("startup_tax"),
        "context_growth_rate": metrics.get("context_growth_rate"),
        "token_cost": int(usage.get("token_cost", 0) or 0),
        "selected_trace_source": item.get("metadata", {}).get("selected_trace_source"),
        "trace_quality": item.get("metadata", {}).get("trace_quality"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
