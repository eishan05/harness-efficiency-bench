"""Execution isolation helpers."""

from __future__ import annotations

from typing import Any

from .manifests import HarnessManifest


def isolation_backend(harness: HarnessManifest) -> str:
    backend = str(harness.config.get("backend", "host"))
    if backend == "docker":
        return "docker"
    return "host"


def describe_isolation(harness: HarnessManifest) -> dict[str, Any]:
    backend = isolation_backend(harness)
    details: dict[str, Any] = {"backend": backend}
    if backend == "docker":
        details.update(
            {
                "docker_image": harness.config.get("docker_image"),
                "docker_network": harness.config.get("docker_network", "bridge"),
                "docker_workspace": harness.config.get("docker_workspace", "/workspace"),
            }
        )
    else:
        details["risk"] = "agent process runs on host with cwd set to the benchmark workspace"
    return details


def require_docker_isolation(harness: HarnessManifest) -> None:
    if isolation_backend(harness) != "docker":
        raise RuntimeError(
            f"harness {harness.id!r} is configured for host execution; "
            "rerun with a Docker-backed harness or omit --require-docker-isolation"
        )
