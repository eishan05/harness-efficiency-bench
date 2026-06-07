"""Task oracle grading."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifests import OracleSpec


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
    return OracleResult(False, 0.0, f"unsupported oracle type: {spec.type}", {})

