"""Result and trace persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .tracing import TraceEvent


class ResultStore:
    def __init__(self, root: str | Path = "runs"):
        self.root = Path(root)
        self.results_dir = self.root / "results"
        self.traces_dir = self.root / "traces"
        self.work_dir = self.root / "work"

    def ensure(self) -> None:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def write_trace(self, run_id: str, events: Iterable[TraceEvent]) -> Path:
        self.ensure()
        path = self.traces_dir / f"{run_id}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        return path

    def write_result(self, run_id: str, result: dict[str, Any]) -> Path:
        self.ensure()
        path = self.results_dir / f"{run_id}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def iter_results(self) -> Iterable[dict[str, Any]]:
        if not self.results_dir.exists():
            return []
        results = []
        for path in sorted(self.results_dir.glob("*.json")):
            results.append(json.loads(path.read_text(encoding="utf-8")))
        return results

