"""Task oracle grading."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git_utils import collect_git_diff
from .manifests import OracleSpec
from .swe_bench import (
    DEFAULT_DOCKER_SOCKET,
    DEFAULT_SWE_BENCH_ORACLE_IMAGE,
    DEFAULT_SWE_BENCH_LITE_DATASET,
    DEFAULT_SWE_BENCH_SPLIT,
    build_swe_bench_docker_command,
    build_swe_bench_eval_command,
    parse_swe_bench_report,
    resolve_swe_bench_arch,
    resolve_swe_bench_namespace,
    swe_bench_report_path,
    write_swe_bench_arch_wrapper,
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
    data = spec.data
    backend = str(data.get("backend", "docker"))
    if backend == "host":
        return _grade_swe_bench_host(spec, workspace)
    if backend == "docker":
        return _grade_swe_bench_docker(spec, workspace)
    return OracleResult(False, 0.0, f"unsupported swe_bench oracle backend: {backend}", {"backend": backend})


def _grade_swe_bench_host(spec: OracleSpec, workspace: Path) -> OracleResult:
    if importlib.util.find_spec("swebench") is None:
        return OracleResult(
            False,
            0.0,
            "swebench package is not installed",
            {"install": "pip install -e '.[swebench]'"},
        )
    prepared = _prepare_swe_bench_eval(spec, workspace)
    if isinstance(prepared, OracleResult):
        return prepared
    wrapper_path = write_swe_bench_arch_wrapper(prepared["eval_root"])
    command = build_swe_bench_eval_command(
        dataset_name=prepared["dataset_name"],
        split=prepared["split"],
        instance_id=prepared["instance_id"],
        predictions_path=prepared["predictions_path"],
        run_id=prepared["run_id"],
        max_workers=prepared["max_workers"],
        cache_level=prepared["cache_level"],
        timeout_sec=prepared["timeout_sec"],
        namespace=prepared["namespace"],
        wrapper_path=wrapper_path,
    )
    return _run_swe_bench_eval(command, prepared, backend="host", extra_env={"SWEBENCH_ARCH": prepared["arch"]})


def _grade_swe_bench_docker(spec: OracleSpec, workspace: Path) -> OracleResult:
    prepared = _prepare_swe_bench_eval(spec, workspace)
    if isinstance(prepared, OracleResult):
        return prepared
    data = spec.data
    docker_socket = str(data.get("docker_socket", DEFAULT_DOCKER_SOCKET))
    if not Path(docker_socket).exists():
        return OracleResult(
            False,
            0.0,
            "Docker socket is not available for SWE-bench oracle",
            {"backend": "docker", "docker_socket": docker_socket},
        )
    evaluator_image = str(data.get("evaluator_image", DEFAULT_SWE_BENCH_ORACLE_IMAGE))
    wrapper_path = write_swe_bench_arch_wrapper(prepared["eval_root"])
    eval_command = build_swe_bench_eval_command(
        dataset_name=prepared["dataset_name"],
        split=prepared["split"],
        instance_id=prepared["instance_id"],
        predictions_path=prepared["predictions_path"],
        run_id=prepared["run_id"],
        max_workers=prepared["max_workers"],
        cache_level=prepared["cache_level"],
        timeout_sec=prepared["timeout_sec"],
        namespace=prepared["namespace"],
        python_executable="python",
        wrapper_path=wrapper_path,
    )
    command = build_swe_bench_docker_command(
        eval_command=eval_command,
        eval_root=prepared["eval_root"],
        evaluator_image=evaluator_image,
        docker_socket=docker_socket,
        swe_bench_arch=prepared["arch"],
    )
    return _run_swe_bench_eval(
        command,
        prepared,
        backend="docker",
        extra_details={
            "arch": prepared["arch"],
            "namespace": prepared["namespace"],
            "evaluator_image": evaluator_image,
            "docker_socket": docker_socket,
        },
    )


def _prepare_swe_bench_eval(spec: OracleSpec, workspace: Path) -> dict[str, Any] | OracleResult:
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
    arch = resolve_swe_bench_arch(data.get("arch", "auto"))
    namespace = resolve_swe_bench_namespace(data.get("namespace", "auto"), arch=arch)

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
    return {
        "instance_id": instance_id,
        "dataset_name": dataset_name,
        "split": split,
        "model_name": model_name,
        "run_id": run_id,
        "max_workers": max_workers,
        "cache_level": cache_level,
        "timeout_sec": timeout_sec,
        "arch": arch,
        "namespace": namespace,
        "eval_root": eval_root,
        "predictions_path": predictions_path,
        "patch": patch,
    }


def _run_swe_bench_eval(
    command: list[str],
    prepared: dict[str, Any],
    *,
    backend: str,
    extra_details: dict[str, Any] | None = None,
    extra_env: dict[str, str] | None = None,
) -> OracleResult:
    eval_root = prepared["eval_root"]
    timeout_sec = int(prepared["timeout_sec"])
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        command,
        cwd=eval_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_sec + 120,
        check=False,
    )
    report_path = swe_bench_report_path(
        eval_root,
        model_name_or_path=str(prepared["model_name"]),
        run_id=str(prepared["run_id"]),
    )
    details: dict[str, Any] = {
        "backend": backend,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "predictions_path": str(prepared["predictions_path"]),
        "report_path": str(report_path),
        "patch_bytes": len(str(prepared["patch"]).encode("utf-8")),
        "arch": prepared.get("arch"),
        "namespace": prepared.get("namespace"),
    }
    if extra_details:
        details.update(extra_details)
    if not report_path.exists():
        return OracleResult(False, 0.0, "swe-bench evaluation report missing", details)

    resolved, report = parse_swe_bench_report(report_path, str(prepared["instance_id"]))
    details["report"] = report
    if completed.returncode != 0 and not resolved:
        return OracleResult(False, 0.0, "swe-bench evaluation failed", details)
    return OracleResult(
        resolved,
        1.0 if resolved else 0.0,
        "swe-bench instance resolved" if resolved else "swe-bench instance unresolved",
        details,
    )
