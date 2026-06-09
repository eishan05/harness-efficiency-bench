"""SWE-bench Lite import and evaluation helpers."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SWE_BENCH_LITE_DATASET = "SWE-bench/SWE-bench_Lite"
DEFAULT_SWE_BENCH_SPLIT = "test"
DEFAULT_SWE_BENCH_ORACLE_IMAGE = "harness-bench/swebench-oracle:4.1.0"
DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"

CURATED_10_INSTANCE_IDS = (
    "django__django-11905",
    "django__django-12308",
    "sympy__sympy-14308",
    "sympy__sympy-13146",
    "matplotlib__matplotlib-23913",
    "matplotlib__matplotlib-24334",
    "pytest-dev__pytest-5221",
    "pytest-dev__pytest-5227",
    "pydata__xarray-3364",
    "pydata__xarray-4248",
)


def fetch_swe_bench_rows(
    *,
    dataset_name: str = DEFAULT_SWE_BENCH_LITE_DATASET,
    split: str = DEFAULT_SWE_BENCH_SPLIT,
    instance_ids: tuple[str, ...] = CURATED_10_INSTANCE_IDS,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch selected SWE-bench rows from the Hugging Face dataset server."""
    wanted = set(instance_ids)
    if not wanted:
        return []
    rows: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": dataset_name,
                "config": "default",
                "split": split,
                "offset": offset,
                "length": page_size,
            }
        )
        with urllib.request.urlopen(f"https://datasets-server.huggingface.co/rows?{query}", timeout=30) as response:
            payload = json.load(response)
        page = payload.get("rows", [])
        if not page:
            break
        for item in page:
            row = item.get("row", {})
            instance_id = row.get("instance_id")
            if instance_id in wanted:
                rows[str(instance_id)] = row
        if len(rows) == len(wanted):
            break
        offset += page_size
    missing = [instance_id for instance_id in instance_ids if instance_id not in rows]
    if missing:
        raise RuntimeError(f"SWE-bench rows not found: {', '.join(missing)}")
    return [rows[instance_id] for instance_id in instance_ids]


def write_swe_bench_task_manifests(
    rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    dataset_name: str = DEFAULT_SWE_BENCH_LITE_DATASET,
    split: str = DEFAULT_SWE_BENCH_SPLIT,
) -> list[Path]:
    """Write benchmark task manifests for SWE-bench rows."""
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        instance_id = str(row["instance_id"])
        repo = str(row["repo"])
        task_dir = out_dir / instance_id
        task_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = task_dir / "prompt.txt"
        prompt = str(row.get("problem_statement", "")).replace("\r\n", "\n").replace("\r", "\n").rstrip()
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        manifest = {
            "id": instance_id,
            "source": "swe-bench-lite",
            "prompt_file": "prompt.txt",
            "workspace_setup": {
                "git_clone": {
                    "repo": repo,
                    "base_commit": str(row["base_commit"]),
                }
            },
            "oracle": {
                "type": "swe_bench",
                "backend": "docker",
                "dataset_name": dataset_name,
                "split": split,
                "instance_id": instance_id,
                "max_workers": 1,
                "cache_level": "env",
                "timeout_sec": 1800,
            },
            "budgets": {
                "timeout_sec": 1800,
            },
            "tags": [
                "swe-bench-lite",
                "curated-10",
                repo.split("/", 1)[-1],
            ],
        }
        manifest_path = task_dir / "task.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        written.append(manifest_path)
    return written


def write_prediction_jsonl(
    path: Path,
    *,
    instance_id: str,
    model_name_or_path: str,
    model_patch: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instance_id": instance_id,
        "model_name_or_path": model_name_or_path,
        "model_patch": model_patch,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def build_swe_bench_eval_command(
    *,
    dataset_name: str,
    split: str,
    instance_id: str,
    predictions_path: Path,
    run_id: str,
    max_workers: int,
    cache_level: str,
    timeout_sec: int,
    namespace: str | None,
    python_executable: str | None = None,
) -> list[str]:
    command = [
        python_executable or sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--predictions_path",
        str(predictions_path),
        "--instance_ids",
        instance_id,
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
        "--cache_level",
        cache_level,
        "--timeout",
        str(timeout_sec),
    ]
    if namespace is not None:
        command.extend(["--namespace", namespace])
    return command


def build_swe_bench_docker_command(
    *,
    eval_command: list[str],
    eval_root: Path,
    evaluator_image: str = DEFAULT_SWE_BENCH_ORACLE_IMAGE,
    docker_socket: str = DEFAULT_DOCKER_SOCKET,
) -> list[str]:
    eval_root = eval_root.resolve()
    docker_socket_gid = Path(docker_socket).stat().st_gid if Path(docker_socket).exists() else os.getgid()
    hf_home = eval_root / ".cache" / "huggingface"
    return [
        "docker",
        "run",
        "--rm",
        "--label",
        "harness-efficiency-bench=true",
        "--label",
        "harness-efficiency-bench.component=swebench-oracle",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--group-add",
        str(docker_socket_gid),
        "-v",
        f"{docker_socket}:{docker_socket}",
        "-e",
        f"DOCKER_HOST=unix://{docker_socket}",
        "-e",
        f"HOME={eval_root}",
        "-e",
        f"HF_HOME={hf_home}",
        "-e",
        f"HF_DATASETS_CACHE={hf_home / 'datasets'}",
        "-e",
        f"HUGGINGFACE_HUB_CACHE={hf_home / 'hub'}",
        "-v",
        f"{eval_root}:{eval_root}",
        "-w",
        str(eval_root),
        evaluator_image,
        *eval_command,
    ]


def swe_bench_report_path(eval_root: Path, *, model_name_or_path: str, run_id: str) -> Path:
    return eval_root / f"{model_name_or_path.replace('/', '__')}.{run_id}.json"


def parse_swe_bench_report(path: Path, instance_id: str) -> tuple[bool, dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    resolved_ids = set(report.get("resolved_ids", []))
    return instance_id in resolved_ids, report
