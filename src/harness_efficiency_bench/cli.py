"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .docker_cleanup import DEFAULT_IMAGE_PREFIXES, SWEBENCH_IMAGE_PREFIXES, execute_docker_cleanup, plan_docker_cleanup
from .manifests import HarnessManifest, TaskManifest
from .runner import DEFAULT_REPO_CACHE, BenchmarkRunner, summarize_results
from .store import ResultStore
from .swe_bench import (
    CURATED_10_INSTANCE_IDS,
    DEFAULT_SWE_BENCH_LITE_DATASET,
    DEFAULT_SWE_BENCH_SPLIT,
    fetch_swe_bench_rows,
    write_swe_bench_task_manifests,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-bench")
    parser.add_argument("--run-root", default="runs", help="Run output directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tasks_parser = subparsers.add_parser("tasks", help="List task manifests.")
    tasks_parser.add_argument("--tasks-dir", default="examples/tasks")
    _add_task_filter_args(tasks_parser)

    harnesses_parser = subparsers.add_parser("harnesses", help="List harness manifests.")
    harnesses_parser.add_argument("--harnesses-dir", default="examples/harnesses")

    run_task_parser = subparsers.add_parser("run-task", help="Run one task/harness pair.")
    run_task_parser.add_argument("--task", required=True)
    run_task_parser.add_argument("--harness", required=True)
    run_task_parser.add_argument("--perturbation")
    run_task_parser.add_argument("--all-perturbations", action="store_true")
    run_task_parser.add_argument("--delete-workspace", action="store_true")
    run_task_parser.add_argument("--require-docker-isolation", action="store_true")
    run_task_parser.add_argument("--repo-cache", help=f"Git mirror cache path. Defaults to {DEFAULT_REPO_CACHE}.")
    run_task_parser.add_argument("--no-repo-cache", action="store_true", help="Disable Git mirror caching.")

    run_suite_parser = subparsers.add_parser("run-suite", help="Run all task manifests with one harness.")
    run_suite_parser.add_argument("--tasks-dir", default="examples/tasks")
    run_suite_parser.add_argument("--harness", required=True)
    run_suite_parser.add_argument("--perturbation")
    run_suite_parser.add_argument("--all-perturbations", action="store_true")
    run_suite_parser.add_argument("--delete-workspace", action="store_true")
    run_suite_parser.add_argument("--require-docker-isolation", action="store_true")
    run_suite_parser.add_argument("--repo-cache", help=f"Git mirror cache path. Defaults to {DEFAULT_REPO_CACHE}.")
    run_suite_parser.add_argument("--no-repo-cache", action="store_true", help="Disable Git mirror caching.")
    _add_task_filter_args(run_suite_parser)

    analyze_parser = subparsers.add_parser("analyze", help="Print raw aggregate JSON.")
    analyze_parser.add_argument("--results-dir")

    report_parser = subparsers.add_parser("report", help="Print markdown aggregate report.")
    report_parser.add_argument("--results-dir")

    export_parser = subparsers.add_parser("export-predictions", help="Export SWE-bench-style prediction JSONL.")
    export_parser.add_argument("--results-dir")
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--model-name")

    import_swe_parser = subparsers.add_parser("import-swe-bench-lite", help="Create SWE-bench Lite task manifests.")
    import_swe_parser.add_argument("--subset", choices=["curated-10"], default="curated-10")
    import_swe_parser.add_argument("--split", default=DEFAULT_SWE_BENCH_SPLIT)
    import_swe_parser.add_argument("--dataset-name", default=DEFAULT_SWE_BENCH_LITE_DATASET)
    import_swe_parser.add_argument("--out-dir", default="examples/tasks/swe-bench-lite-curated-10")

    cleanup_parser = subparsers.add_parser("cleanup-docker", help="Clean benchmark Docker artifacts.")
    cleanup_parser.add_argument(
        "--force",
        action="store_true",
        help="Actually remove resources. Without this flag, prints a dry-run plan.",
    )
    cleanup_parser.add_argument(
        "--include-build-cache",
        action="store_true",
        help="Also run docker builder prune -f.",
    )
    cleanup_parser.add_argument(
        "--include-swebench",
        action="store_true",
        help="Also remove official SWE-bench evaluation images with sweb.* repositories.",
    )
    cleanup_parser.add_argument(
        "--image-prefix",
        action="append",
        default=None,
        help="Image repository prefix to remove. May be repeated. Defaults to harness-bench/.",
    )

    args = parser.parse_args(argv)
    if args.command == "tasks":
        return _list_task_manifests(Path(args.tasks_dir), args)
    if args.command == "harnesses":
        return _list_manifests(Path(args.harnesses_dir), HarnessManifest.load)
    if args.command == "run-task":
        runner = BenchmarkRunner(
            args.run_root,
            require_docker=args.require_docker_isolation,
            repo_cache=_repo_cache_from_args(args),
        )
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
        runner = BenchmarkRunner(
            args.run_root,
            require_docker=args.require_docker_isolation,
            repo_cache=_repo_cache_from_args(args),
        )
        harness = HarnessManifest.load(args.harness)
        results = []
        try:
            for task_path in _manifest_paths(Path(args.tasks_dir)):
                task = TaskManifest.load(task_path)
                if not _task_matches_tag_filters(task, args):
                    continue
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
    if args.command == "import-swe-bench-lite":
        rows = fetch_swe_bench_rows(
            dataset_name=args.dataset_name,
            split=args.split,
            instance_ids=CURATED_10_INSTANCE_IDS,
        )
        written = write_swe_bench_task_manifests(
            rows,
            Path(args.out_dir),
            dataset_name=args.dataset_name,
            split=args.split,
        )
        print(
            json.dumps(
                {
                    "subset": args.subset,
                    "dataset_name": args.dataset_name,
                    "split": args.split,
                    "out_dir": args.out_dir,
                    "count": len(written),
                    "tasks": [str(path) for path in written],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "cleanup-docker":
        prefixes = tuple(args.image_prefix or DEFAULT_IMAGE_PREFIXES)
        if args.include_swebench:
            prefixes = (*prefixes, *SWEBENCH_IMAGE_PREFIXES)
        plan = plan_docker_cleanup(image_prefixes=prefixes, include_build_cache=args.include_build_cache)
        result = execute_docker_cleanup(plan, dry_run=not args.force)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _manifest_paths(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted([*root.glob("*/task.yaml"), *root.glob("*.yaml"), *root.glob("*.json")])


def _add_task_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-tag", action="append", default=[], help="Only include tasks with this tag.")
    parser.add_argument("--exclude-tag", action="append", default=[], help="Exclude tasks with this tag.")


def _task_matches_tag_filters(task: TaskManifest, args: argparse.Namespace) -> bool:
    include_tags = set(getattr(args, "include_tag", []) or [])
    exclude_tags = set(getattr(args, "exclude_tag", []) or [])
    tags = set(task.tags)
    return include_tags.issubset(tags) and not tags.intersection(exclude_tags)


def _list_task_manifests(root: Path, args: argparse.Namespace) -> int:
    items = []
    for path in _manifest_paths(root):
        try:
            manifest = TaskManifest.load(path)
        except Exception as exc:
            items.append({"path": str(path), "error": str(exc)})
            continue
        if not _task_matches_tag_filters(manifest, args):
            continue
        items.append({"id": manifest.id, "path": str(path)})
    print(json.dumps(items, indent=2, sort_keys=True))
    return 0


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


def _repo_cache_from_args(args: argparse.Namespace) -> Path | None:
    if getattr(args, "no_repo_cache", False):
        return None
    raw = getattr(args, "repo_cache", None)
    return Path(raw) if raw else DEFAULT_REPO_CACHE


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
        f"- Solved (strict): {summary['solved']}",
        f"- Solve rate (strict): {summary['solve_rate']:.3f}",
        f"- Solved (oracle): {summary['oracle_solved']}",
        f"- Solve rate (oracle): {summary['oracle_solve_rate']:.3f}",
        f"- Token cost: {summary['token_cost']}",
        f"- Token cost per solved task (strict): {summary['token_cost_per_solved_task']}",
        f"- Token cost per solved task (oracle): {summary['token_cost_per_oracle_solved_task']}",
        f"- Cost USD: {summary['cost_usd']:.6f}",
        f"- Dollar cost per solved task (strict): {summary['dollar_cost_per_solved_task']}",
        f"- Dollar cost per solved task (oracle): {summary['dollar_cost_per_oracle_solved_task']}",
        "",
        "| Harness | Attempted | Solved | Oracle Solved | Solve Rate | Token Cost | Tokens / Solved | Tokens / Oracle-Solved | Cost USD | USD / Solved | Startup Tax | Growth |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for harness_id, bucket in sorted(summary["by_harness"].items()):
        token_cost_per = bucket["token_cost_per_solved_task"]
        token_cost_per_text = "" if token_cost_per is None else f"{token_cost_per:.3f}"
        oracle_token_cost_per = bucket["token_cost_per_oracle_solved_task"]
        oracle_token_cost_per_text = "" if oracle_token_cost_per is None else f"{oracle_token_cost_per:.3f}"
        dollar_cost_per = bucket["dollar_cost_per_solved_task"]
        dollar_cost_per_text = "" if dollar_cost_per is None else f"{dollar_cost_per:.6f}"
        metrics = bucket.get("metrics", {})
        startup = _optional_number(metrics.get("startup_tax", {}).get("avg"))
        growth = _optional_number(metrics.get("context_growth_rate", {}).get("avg"))
        lines.append(
            f"| {harness_id} | {bucket['attempted']} | {bucket['solved']} | {bucket['oracle_solved']} | "
            f"{bucket['solve_rate']:.3f} | {bucket['token_cost']} | {token_cost_per_text} | "
            f"{oracle_token_cost_per_text} | "
            f"{bucket['cost_usd']:.6f} | {dollar_cost_per_text} | "
            f"{startup} | {growth} |"
        )
    if summary.get("by_perturbation"):
        lines.extend(
            [
                "",
                "## Perturbations",
                "",
                "| Perturbation | Attempted | Solved | Oracle Solved | Solve Rate |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for perturbation_id, bucket in sorted(summary["by_perturbation"].items()):
            lines.append(
                f"| {perturbation_id} | {bucket['attempted']} | {bucket['solved']} | "
                f"{bucket['oracle_solved']} | {bucket['solve_rate']:.3f} |"
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
