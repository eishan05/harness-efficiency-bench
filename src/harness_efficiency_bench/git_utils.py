"""Git helpers used by benchmark workspaces."""

from __future__ import annotations

import subprocess
from pathlib import Path


def collect_git_diff(workspace: Path) -> str:
    """Collect the model patch from a Git-initialized benchmark workspace."""
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
            ":(exclude).codex_rollout_trace/**",
            ":(exclude)**/.codex_rollout_trace",
            ":(exclude)__pycache__/**",
            ":(exclude)**/__pycache__/**",
            ":(exclude).pytest_cache/**",
            ":(exclude)**/.pytest_cache/**",
            ":(exclude).mypy_cache/**",
            ":(exclude)**/.mypy_cache/**",
            ":(exclude).ruff_cache/**",
            ":(exclude)**/.ruff_cache/**",
            ":(exclude).tox/**",
            ":(exclude)**/.tox/**",
            ":(exclude).nox/**",
            ":(exclude)**/.nox/**",
            ":(exclude).coverage",
            ":(exclude)**/.coverage",
            ":(exclude)htmlcov/**",
            ":(exclude)**/htmlcov/**",
        ],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else ""
