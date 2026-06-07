"""Utilities for command-based adapters."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .base import AdapterResult, AdapterRunContext
from ..tracing import TraceEvent


def render_command(
    command: str | list[str],
    context: AdapterRunContext,
    *,
    workspace_override: str | None = None,
    prompt_file_override: str | None = None,
) -> str | list[str]:
    values = {
        "prompt": context.prompt,
        "prompt_file": prompt_file_override or str(context.prompt_file),
        "workspace": workspace_override or str(context.workspace),
        "run_id": context.run_id,
        "task_id": context.task.id,
        "harness_id": context.harness.id,
        "model": context.harness.model or "",
        "model_endpoint": context.harness.model_endpoint or "",
    }
    if isinstance(command, list):
        return [part.format(**values) for part in command]
    return command.format(**{key: shlex.quote(value) for key, value in values.items()})


def merged_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    return env


def run_command(
    command: str | list[str],
    context: AdapterRunContext,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if context.harness.config.get("backend") == "docker":
        return run_docker_command(command, context, stdin=stdin)
    rendered = render_command(command, context)
    shell = isinstance(rendered, str)
    return subprocess.run(
        rendered,
        cwd=context.workspace,
        env=merged_env(context.harness.env),
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=context.timeout_sec,
        shell=shell,
        check=False,
    )


def run_docker_command(
    command: str | list[str],
    context: AdapterRunContext,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    docker_command = build_docker_command(command, context)
    return subprocess.run(
        docker_command,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=context.timeout_sec,
        check=False,
    )


def build_docker_command(command: str | list[str], context: AdapterRunContext) -> list[str]:
    image = context.harness.config.get("docker_image")
    if not image:
        raise ValueError("docker backend requires config.docker_image")
    docker_workspace = str(context.harness.config.get("docker_workspace", "/workspace"))
    docker_prompt_file = f"{docker_workspace}/{context.prompt_file.name}"
    rendered = render_command(
        command,
        context,
        workspace_override=docker_workspace,
        prompt_file_override=docker_prompt_file,
    )
    docker_command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{context.workspace.resolve()}:{docker_workspace}",
        "-w",
        docker_workspace,
    ]
    network = context.harness.config.get("docker_network", "bridge")
    if network:
        docker_command.extend(["--network", str(network)])
    docker_user = context.harness.config.get("docker_user")
    if docker_user:
        docker_command.extend(["--user", str(docker_user)])
    docker_memory = context.harness.config.get("docker_memory")
    if docker_memory:
        docker_command.extend(["--memory", str(docker_memory)])
    docker_cpus = context.harness.config.get("docker_cpus")
    if docker_cpus:
        docker_command.extend(["--cpus", str(docker_cpus)])
    if context.harness.config.get("docker_read_only"):
        docker_command.append("--read-only")
    docker_home = context.harness.config.get("docker_home")
    if docker_home:
        docker_command.extend(["-e", f"HOME={docker_home}"])
    for tmpfs in context.harness.config.get("docker_tmpfs", []):
        docker_command.extend(["--tmpfs", str(tmpfs)])
    for mount in context.harness.config.get("docker_mounts", []):
        docker_command.extend(_docker_mount_args(mount))
    for key, value in context.harness.env.items():
        docker_command.extend(["-e", f"{key}={value}"])
    for key in context.harness.config.get("docker_env_passthrough", []):
        value = os.environ.get(str(key))
        if value is not None:
            docker_command.extend(["-e", f"{key}={value}"])
    docker_command.append(str(image))
    if isinstance(rendered, str):
        docker_command.extend(["/bin/sh", "-lc", rendered])
    else:
        docker_command.extend(rendered)
    return docker_command


def _docker_mount_args(mount: object) -> list[str]:
    if isinstance(mount, str):
        return ["-v", mount]
    if not isinstance(mount, dict):
        raise ValueError(f"docker_mounts entries must be strings or objects: {mount!r}")
    source = mount.get("source")
    target = mount.get("target")
    if not source or not target:
        raise ValueError(f"docker mount requires source and target: {mount!r}")
    source_path = Path(os.path.expandvars(os.path.expanduser(str(source)))).resolve()
    suffix = ":ro" if mount.get("read_only") else ""
    return ["-v", f"{source_path}:{target}{suffix}"]


def parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            events.append(raw)
    return events


def collect_workspace_diff(workspace: Path) -> str:
    completed = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else ""


def result_from_completed(completed: subprocess.CompletedProcess[str]) -> AdapterResult:
    return AdapterResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        trace_events=[TraceEvent(type="adapter_output", data={"stdout": completed.stdout, "stderr": completed.stderr})],
    )
