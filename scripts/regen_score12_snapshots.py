#!/usr/bin/env python3
"""Regenerate score-12 snapshot files in place from their raw run roots,
reusing each snapshot's own recorded metadata (suite, execution, commands)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def regen(snapshot_path: Path, run_root: Path) -> None:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    benchmark = payload["benchmark"]
    harness = payload["harness"]
    command = [
        sys.executable,
        str(ROOT / "scripts/save_result_snapshot.py"),
        "--run-root",
        str(run_root),
        "--out",
        str(snapshot_path),
        "--harness",
        harness["base_manifest"],
        "--model",
        harness["model"],
        "--suite",
        benchmark["suite"],
        "--tasks-dir",
        benchmark["tasks_dir"],
        "--perturbation-mode",
        benchmark["perturbation_mode"],
        "--oracle-mode",
        benchmark["oracle_mode"],
        "--execution",
        harness["execution"],
    ]
    for recorded in payload.get("commands") or []:
        command.extend(["--command", recorded])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if completed.returncode != 0:
        raise SystemExit(f"regen failed for {snapshot_path}:\n{completed.stderr}")
    print(f"regenerated {snapshot_path.name}")


def main() -> int:
    base = ROOT / "runs"
    results = ROOT / "examples/results"
    for snapshot_path in sorted(results.glob("*deepseek-v4-flash-non-swe-score-12*.json")):
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        harness_id = payload["harness"]["id"]
        if "architect" in snapshot_path.name:
            run_root = base / "openrouter-deepseek-v4-flash-non-swe-score-12-aider-architect-20260609" / harness_id
        else:
            run_root = base / "openrouter-deepseek-v4-flash-non-swe-score-12-20260609" / harness_id
        if not run_root.exists():
            raise SystemExit(f"missing run root {run_root}")
        regen(snapshot_path, run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
