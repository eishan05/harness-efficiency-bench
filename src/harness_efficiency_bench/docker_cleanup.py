"""Docker cleanup helpers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


DEFAULT_IMAGE_PREFIXES = ("harness-bench/",)
BENCHMARK_CONTAINER_LABEL = "harness-efficiency-bench=true"


@dataclass(slots=True)
class DockerCleanupPlan:
    containers: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    prune_build_cache: bool = False

    def to_dict(self, *, dry_run: bool) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "containers": self.containers,
            "images": self.images,
            "prune_build_cache": self.prune_build_cache,
        }


def plan_docker_cleanup(
    *,
    image_prefixes: tuple[str, ...] = DEFAULT_IMAGE_PREFIXES,
    include_build_cache: bool = False,
) -> DockerCleanupPlan:
    return DockerCleanupPlan(
        containers=_docker_lines(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label={BENCHMARK_CONTAINER_LABEL}",
            ]
        ),
        images=_benchmark_images(image_prefixes),
        prune_build_cache=include_build_cache,
    )


def execute_docker_cleanup(plan: DockerCleanupPlan, *, dry_run: bool = True) -> dict[str, Any]:
    result = plan.to_dict(dry_run=dry_run)
    if dry_run:
        return result
    if plan.containers:
        _run(["docker", "rm", "-f", *plan.containers])
    if plan.images:
        _run(["docker", "rmi", *plan.images])
    if plan.prune_build_cache:
        _run(["docker", "builder", "prune", "-f"])
    return result


def _benchmark_images(prefixes: tuple[str, ...]) -> list[str]:
    images: list[str] = []
    rows = _docker_lines(["docker", "images", "--format", "{{json .}}"])
    for row in rows:
        try:
            item = json.loads(row)
        except json.JSONDecodeError:
            continue
        repository = str(item.get("Repository", ""))
        tag = str(item.get("Tag", ""))
        image_id = str(item.get("ID", ""))
        if repository.startswith(prefixes):
            images.append(f"{repository}:{tag}" if tag and tag != "<none>" else image_id)
    return images


def _docker_lines(command: list[str]) -> list[str]:
    completed = _run(command, check=False)
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
