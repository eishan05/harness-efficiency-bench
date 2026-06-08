"""Task oracle grading."""

from __future__ import annotations

import importlib.util
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git_utils import collect_git_diff
from .manifests import OracleSpec
from .swe_bench import (
    DEFAULT_SWE_BENCH_LITE_DATASET,
    DEFAULT_SWE_BENCH_SPLIT,
    build_swe_bench_eval_command,
    parse_swe_bench_report,
    swe_bench_report_path,
    write_prediction_jsonl,
)


@dataclass(slots=True)
class OracleResult:
    success: bool
    score: float
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "score": self.score,
            "message": self.message,
            "details": self.details,
        }


def grade_oracle(spec: OracleSpec, workspace: Path) -> OracleResult:
    if spec.type == "none":
        return OracleResult(True, 1.0, "no oracle configured", {})
    if spec.type == "file_equals":
        if not spec.path:
            return OracleResult(False, 0.0, "file_equals oracle missing path", {})
        target = workspace / spec.path
        if not target.exists():
            return OracleResult(False, 0.0, f"expected file missing: {spec.path}", {})
        actual = target.read_text(encoding="utf-8")
        expected = spec.text or ""
        success = actual == expected
        return OracleResult(
            success,
            1.0 if success else 0.0,
            "file matched" if success else "file content mismatch",
            {"path": spec.path, "expected": expected, "actual": actual},
        )
    if spec.type == "file_contains":
        if not spec.path:
            return OracleResult(False, 0.0, "file_contains oracle missing path", {})
        target = workspace / spec.path
        if not target.exists():
            return OracleResult(False, 0.0, f"expected file missing: {spec.path}", {})
        actual = target.read_text(encoding="utf-8")
        needle = spec.text or ""
        success = needle in actual
        return OracleResult(
            success,
            1.0 if success else 0.0,
            "file contained text" if success else "file did not contain text",
            {"path": spec.path, "needle": needle},
        )
    if spec.type == "command":
        if not spec.command:
            return OracleResult(False, 0.0, "command oracle missing command", {})
        completed = subprocess.run(
            spec.command,
            cwd=workspace,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=spec.timeout_sec,
            check=False,
        )
        success = completed.returncode == 0
        return OracleResult(
            success,
            1.0 if success else 0.0,
            "command passed" if success else "command failed",
            {
                "command": spec.command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
    if spec.type == "swe_bench":
        return _grade_swe_bench(spec, workspace)
    return OracleResult(False, 0.0, f"unsupported oracle type: {spec.type}", {})


def _grade_swe_bench(spec: OracleSpec, workspace: Path) -> OracleResult:
    if importlib.util.find_spec("swebench") is None:
        return OracleResult(
            False,
            0.0,
            "swebench package is not installed",
            {"install": "pip install -e '.[swebench]'"},
        )
    data = spec.data
    instance_id = str(data.get("instance_id") or "")
    if not instance_id:
        return OracleResult(False, 0.0, "swe_bench oracle missing instance_id", {})

    dataset_name = str(data.get("dataset_name", DEFAULT_SWE_BENCH_LITE_DATASET))
    split = str(data.get("split", DEFAULT_SWE_BENCH_SPLIT))
    model_name = str(data.get("model_name_or_path", "harness-efficiency-bench"))
    run_id = str(data.get("run_id") or f"{instance_id}-{uuid.uuid4().hex[:10]}")
    max_workers = int(data.get("max_workers", 1))
    cache_level = str(data.get("cache_level", "env"))
    timeout_sec = int(data.get("timeout_sec", spec.timeout_sec))
    namespace_raw = data.get("namespace", "swebench")
    namespace = None if namespace_raw is None else str(namespace_raw)

    eval_root = (workspace.parent / "swebench_eval").resolve()
    eval_root.mkdir(parents=True, exist_ok=True)
    predictions_path = eval_root / "predictions.jsonl"
    patch = collect_git_diff(workspace)
    write_prediction_jsonl(
        predictions_path,
        instance_id=instance_id,
        model_name_or_path=model_name,
        model_patch=patch,
    )
    command = build_swe_bench_eval_command(
        dataset_name=dataset_name,
        split=split,
        instance_id=instance_id,
        predictions_path=predictions_path,
        run_id=run_id,
        max_workers=max_workers,
        cache_level=cache_level,
        timeout_sec=timeout_sec,
        namespace=namespace,
    )
    completed = subprocess.run(
        command,
        cwd=eval_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_sec + 120,
        check=False,
    )
    report_path = swe_bench_report_path(eval_root, model_name_or_path=model_name, run_id=run_id)
    details: dict[str, Any] = {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "predictions_path": str(predictions_path),
        "report_path": str(report_path),
        "patch_bytes": len(patch.encode("utf-8")),
    }
    if not report_path.exists():
        return OracleResult(False, 0.0, "swe-bench evaluation report missing", details)

    resolved, report = parse_swe_bench_report(report_path, instance_id)
    details["report"] = report
    if completed.returncode != 0 and not resolved:
        return OracleResult(False, 0.0, "swe-bench evaluation failed", details)
    return OracleResult(
        resolved,
        1.0 if resolved else 0.0,
        "swe-bench instance resolved" if resolved else "swe-bench instance unresolved",
        details,
    )
