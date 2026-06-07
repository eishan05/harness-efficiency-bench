"""Adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..manifests import HarnessManifest, TaskManifest
from ..tracing import TraceEvent


@dataclass(slots=True)
class AdapterResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    trace_events: list[TraceEvent] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdapterRunContext:
    run_id: str
    task: TaskManifest
    harness: HarnessManifest
    workspace: Path
    prompt: str
    prompt_file: Path
    timeout_sec: int


class BaseAdapter:
    """Base class for all harness adapters."""

    name = "base"

    def __init__(self, manifest: HarnessManifest):
        self.manifest = manifest

    def run(self, context: AdapterRunContext) -> AdapterResult:
        raise NotImplementedError

