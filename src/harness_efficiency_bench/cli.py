"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .manifests import HarnessManifest, TaskManifest
from .runner import BenchmarkRunner, summarize_results
from .store import ResultStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-bench")
    parser.add_argument("--run-root", default="runs", help="Run output directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tasks_parser = subparsers.add_parser("tasks", help="List task manifests.")
    tasks_parser.add_argument("--tasks-dir", default="examples/tasks")

    harnesses_parser = subparsers.add_parser("harnesses", help="List harness manifests.")
    harnesses_parser.add_argument("--harnesses-dir", default="examples/harnesses")

    run_task_parser = subparsers.add_parser("run-task", help="Run one task/harness pair.")
    run_task_parser.add_argument("--task", required=True)
    run_task_parser.add_argument("--harness", required=True)
    run_task_parser.add_argument("--perturbation")
    run_task_parser.add_argument("--all-perturbations", action="store_true")
    run_task_parser.add_argument("--delete-workspace", action="store_true")
    run_task_parser.add_argument("--require-docker-isolation", action="store_true")

    run_suite_parser = subparsers.add_parser("run-suite", help="Run all task manifests with one harness.")
    run_suite_parser.add_argument("--tasks-dir", default="examples/tasks")
    run_suite_parser.add_argument("--harness", required=True)
    run_suite_parser.add_argument("--perturbation")
    run_suite_parser.add_argument("--all-perturbations", action="store_true")
    run_suite_parser.add_argument("--delete-workspace", action="store_true")
    run_suite_parser.add_argument("--require-docker-isolation", action="store_true")

    analyze_parser = subparsers.add_parser("analyze", help="Print raw aggregate JSON.")
    analyze_parser.add_argument("--results-dir")

    report_parser = subparsers.add_parser("report", help="Print markdown aggregate report.")
    report_parser.add_argument("--results-dir")

    export_parser = subparsers.add_parser("export-predictions", help="Export SWE-bench-style prediction JSONL.")
    export_parser.add_argument("--results-dir")
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--model-name")

    args = parser.parse_args(argv)
    if args.command == "tasks":
        return _list_manifests(Path(args.tasks_dir), TaskManifest.load)
    if args.command == "harnesses":
        return _list_manifests(Path(args.harnesses_dir), HarnessManifest.load)
    if args.command == "run-task":
        runner = BenchmarkRunner(args.run_root, require_docker=args.require_docker_isolation)
        task = TaskManifest.load(args.task)
        harness = HarnessManifest.load(args.harness)
        try:
            results = _run_task_with_perturbations(runner, task, harness, args)
        except RuntimeError as exc:
            parser.error(str(exc))
        payload = results[0] if len(results) == 1 else {"summary": summarize_results(results), "results": results}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if all(item["success"] for item in results) else 1
    if args.command == "run-suite":
        runner = BenchmarkRunner(args.run_root, require_docker=args.require_docker_isolation)
        harness = HarnessManifest.load(args.harness)
        results = []
        try:
            for task_path in _manifest_paths(Path(args.tasks_dir)):
                task = TaskManifest.load(task_path)
                results.extend(_run_task_with_perturbations(runner, task, harness, args))
        except RuntimeError as exc:
            parser.error(str(exc))
        summary = summarize_results(results)
        print(json.dumps({"summary": summary, "results": results}, indent=2, sort_keys=True))
        return 0 if all(item["success"] for item in results) else 1
    if args.command == "analyze":
        results = _load_results(args)
        print(json.dumps(summarize_results(results), indent=2, sort_keys=True))
        return 0
    if args.command == "report":
        results = _load_results(args)
        print(_markdown_report(summarize_results(results)))
        return 0
    if args.command == "export-predictions":
        results = _load_results(args)
        _export_predictions(results, Path(args.out), args.model_name)
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _manifest_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted([*root.glob("*/task.yaml"), *root.glob("*.yaml"), *root.glob("*.json")])


def _list_manifests(root: Path, loader: Any) -> int:
    items = []
    for path in _manifest_paths(root):
        try:
            manifest = loader(path)
        except Exception as exc:
            items.append({"path": str(path), "error": str(exc)})
            continue
        items.append({"id": manifest.id, "path": str(path)})
    print(json.dumps(items, indent=2, sort_keys=True))
    return 0


def _load_results(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.results_dir:
        store = ResultStore(Path(args.results_dir).parent)
        store.results_dir = Path(args.results_dir)
    else:
        store = ResultStore(args.run_root)
    return list(store.iter_results())


def _run_task_with_perturbations(
    runner: BenchmarkRunner,
    task: TaskManifest,
    harness: HarnessManifest,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    if args.all_perturbations:
        perturbation_ids: list[str | None] = [None] + [item.id for item in task.perturbations]
    else:
        perturbation_ids = [args.perturbation]
    return [
        runner.run_task(
            task,
            harness,
            perturbation_id=perturbation_id,
            keep_workspace=not args.delete_workspace,
        )
        for perturbation_id in perturbation_ids
    ]


def _markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Harness Efficiency Report",
        "",
        f"- Attempted: {summary['attempted']}",
        f"- Solved: {summary['solved']}",
        f"- Solve rate: {summary['solve_rate']:.3f}",
        f"- Cost USD: {summary['cost_usd']:.6f}",
        f"- Cost per solved task: {summary['cost_per_solved_task']}",
        "",
        "| Harness | Attempted | Solved | Solve Rate | Cost USD | Cost / Solved | Startup Tax | Growth | Retention |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for harness_id, bucket in sorted(summary["by_harness"].items()):
        cost_per = bucket["cost_per_solved_task"]
        cost_per_text = "" if cost_per is None else f"{cost_per:.6f}"
        metrics = bucket.get("metrics", {})
        startup = _optional_number(metrics.get("startup_tax", {}).get("avg"))
        growth = _optional_number(metrics.get("context_growth_rate", {}).get("avg"))
        retention = _optional_number(metrics.get("tool_output_retention_ratio", {}).get("avg"))
        lines.append(
            f"| {harness_id} | {bucket['attempted']} | {bucket['solved']} | "
            f"{bucket['solve_rate']:.3f} | {bucket['cost_usd']:.6f} | {cost_per_text} | "
            f"{startup} | {growth} | {retention} |"
        )
    if summary.get("by_perturbation"):
        lines.extend(
            [
                "",
                "## Context Bloat",
                "",
                "| Perturbation | Attempted | Solved | Solve Rate |",
                "|---|---:|---:|---:|",
            ]
        )
        for perturbation_id, bucket in sorted(summary["by_perturbation"].items()):
            lines.append(
                f"| {perturbation_id} | {bucket['attempted']} | {bucket['solved']} | {bucket['solve_rate']:.3f} |"
            )
    coverage = summary.get("research_metric_coverage")
    if coverage:
        lines.extend(
            [
                "",
                "## Research Metric Coverage",
                "",
                "| Metric | Status | Requirement |",
                "|---|---|---|",
            ]
        )
        for metric_name, item in coverage.items():
            lines.append(f"| {metric_name} | {item.get('status', '')} | {item.get('requirement', '')} |")
    return "\n".join(lines)


def _optional_number(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value):.6f}"


def _export_predictions(results: list[dict[str, Any]], out_path: Path, model_name: str | None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for result in results:
            patch = result.get("artifacts", {}).get("git_diff", "")
            prediction = {
                "instance_id": result.get("task_id"),
                "model_name_or_path": model_name or result.get("harness_id"),
                "model_patch": patch,
            }
            handle.write(json.dumps(prediction, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
