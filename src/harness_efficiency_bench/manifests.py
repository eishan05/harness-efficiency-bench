"""Manifest loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


def load_mapping(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise ManifestError(f"manifest does not exist: {manifest_path}")
    text = manifest_path.read_text(encoding="utf-8")
    if manifest_path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ManifestError(f"manifest must contain an object: {manifest_path}")
    return data


@dataclass(slots=True)
class OracleSpec:
    type: str
    path: str | None = None
    text: str | None = None
    command: str | None = None
    timeout_sec: int = 120
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "OracleSpec":
        if not raw:
            return cls(type="none")
        known_keys = {"type", "path", "text", "command", "timeout_sec"}
        return cls(
            type=str(raw.get("type", "none")),
            path=raw.get("path"),
            text=raw.get("text"),
            command=raw.get("command"),
            timeout_sec=int(raw.get("timeout_sec", 120)),
            data={str(k): v for k, v in raw.items() if k not in known_keys},
        )


@dataclass(slots=True)
class PerturbationSpec:
    id: str
    tokens: int = 0
    seed: str = "irrelevant stale context"
    placement: str = "prompt_prefix"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PerturbationSpec":
        return cls(
            id=str(raw["id"]),
            tokens=int(raw.get("tokens", 0)),
            seed=str(raw.get("seed", "irrelevant stale context")),
            placement=str(raw.get("placement", "prompt_prefix")),
        )


@dataclass(slots=True)
class TaskManifest:
    id: str
    prompt: str
    path: Path
    source: str = "local"
    fixtures: str | None = None
    workspace_setup: dict[str, Any] = field(default_factory=dict)
    oracle: OracleSpec = field(default_factory=lambda: OracleSpec(type="none"))
    budgets: dict[str, Any] = field(default_factory=dict)
    perturbations: list[PerturbationSpec] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "TaskManifest":
        manifest_path = Path(path)
        raw = load_mapping(manifest_path)
        if "id" not in raw:
            raise ManifestError(f"task manifest missing id: {manifest_path}")
        if "prompt" not in raw and "prompt_file" not in raw:
            raise ManifestError(f"task manifest missing prompt or prompt_file: {manifest_path}")
        prompt = str(raw.get("prompt", ""))
        if "prompt_file" in raw:
            prompt_file = manifest_path.parent / str(raw["prompt_file"])
            prompt = prompt_file.read_text(encoding="utf-8")
        return cls(
            id=str(raw["id"]),
            source=str(raw.get("source", "local")),
            prompt=prompt,
            path=manifest_path,
            fixtures=raw.get("fixtures"),
            workspace_setup=dict(raw.get("workspace_setup", {})),
            oracle=OracleSpec.from_dict(raw.get("oracle")),
            budgets=dict(raw.get("budgets", {})),
            perturbations=[PerturbationSpec.from_dict(item) for item in raw.get("perturbations", [])],
            tags=[str(item) for item in raw.get("tags", [])],
        )

    def perturbation(self, perturbation_id: str | None) -> PerturbationSpec | None:
        if not perturbation_id:
            return None
        for item in self.perturbations:
            if item.id == perturbation_id:
                return item
        raise ManifestError(f"unknown perturbation {perturbation_id!r} for task {self.id}")


@dataclass(slots=True)
class HarnessManifest:
    id: str
    adapter: str
    path: Path
    command: str | list[str] | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    model_endpoint: str | None = None
    timeout_sec: int = 900
    trace_mode: str = "partial"
    permissions: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    pricing: dict[str, float] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "HarnessManifest":
        manifest_path = Path(path)
        raw = load_mapping(manifest_path)
        if "id" not in raw:
            raise ManifestError(f"harness manifest missing id: {manifest_path}")
        if "adapter" not in raw:
            raise ManifestError(f"harness manifest missing adapter: {manifest_path}")
        return cls(
            id=str(raw["id"]),
            adapter=str(raw["adapter"]),
            command=raw.get("command"),
            args=[str(item) for item in raw.get("args", [])],
            env={str(k): str(v) for k, v in dict(raw.get("env", {})).items()},
            model=raw.get("model"),
            model_endpoint=raw.get("model_endpoint"),
            timeout_sec=int(raw.get("timeout_sec", 900)),
            trace_mode=str(raw.get("trace_mode", "partial")),
            permissions=dict(raw.get("permissions", {})),
            capabilities=[str(item) for item in raw.get("capabilities", [])],
            pricing={str(k): float(v) for k, v in dict(raw.get("pricing", {})).items()},
            config=dict(raw.get("config", {})),
            path=manifest_path,
        )
