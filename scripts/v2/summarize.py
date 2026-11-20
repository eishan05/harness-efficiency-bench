#!/usr/bin/env python3
"""Summarize a v2 run folder (runs/v2/RUN_NAME): one row per harness.

    python3 scripts/v2/summarize.py runs/v2/RUN_NAME

Columns: tasks attempted and solved (strict and oracle), model calls seen by the
proxy, input / cached / output tokens, tokens per oracle-solved task, mean startup
tax, which trace source the bench used, and two checks for the Go setup: how many
distinct proxy session ids there were per task run (should be 1), and whether any call
asked for a different model than the one under test (requested_model).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def harness_row(folder: Path) -> dict:
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "results").glob("*.json"))]
    row = {
        "harness": folder.name,
        "runs": len(results),
        "solved": sum(1 for r in results if r.get("success")),
        "oracle": sum(1 for r in results if (r.get("oracle_result") or {}).get("success")),
        "calls": 0,
        "input": 0,
        "cached": 0,
        "output": 0,
        "token_cost": sum(int(((r.get("metrics") or {}).get("usage") or {}).get("token_cost") or 0) for r in results),
        "startup": [],
        "sources": set(),
        "multi_session_runs": 0,
        "requested_models": set(),
        "models": set(),
        "exit_codes": set(),
    }
    for r in results:
        row["sources"].add((r.get("metadata") or {}).get("selected_trace_source") or "-")
        row["exit_codes"].add(r.get("adapter_exit_code"))
        tax = ((r.get("metrics") or {}).get("startup_tax") or {}).get("value")
        if tax is not None:
            row["startup"].append(tax)
        run_id = r.get("run_id")
        trace = folder / "traces" / f"{run_id}.jsonl" if run_id else None
        if not trace or not trace.exists():
            continue
        sessions = set()
        for event in load_jsonl(trace):
            if event.get("type") != "model_call":
                continue
            data = event  # trace events keep their fields at the top level
            meta = data.get("metadata") or {}
            if meta.get("source") != "usage_proxy":
                continue
            row["calls"] += 1
            row["input"] += int(data.get("input_tokens") or 0)
            row["cached"] += int(data.get("cached_input_tokens") or 0)
            row["output"] += int(data.get("output_tokens") or 0)
            if meta.get("session_id"):
                sessions.add(meta["session_id"])
            if meta.get("requested_model"):
                row["requested_models"].add(meta["requested_model"])
            if meta.get("model"):
                row["models"].add(meta["model"])
        if len(sessions) > 1:
            row["multi_session_runs"] += 1
    return row


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base = Path(sys.argv[1])
    rows = [harness_row(d) for d in sorted(base.iterdir()) if d.is_dir() and (d / "results").exists()]
    header = ("harness", "solved", "oracle", "calls", "input", "cached", "output", "tok/oracle-solved",
              "startup", "source", "exit", "sessions>1", "models", "requested")
    print(" | ".join(header))
    print(" | ".join("---" for _ in header))
    for r in rows:
        per_solved = round(r["token_cost"] / r["oracle"]) if r["oracle"] else "-"
        startup = round(sum(r["startup"]) / len(r["startup"])) if r["startup"] else "-"
        print(" | ".join(str(x) for x in (
            r["harness"], f"{r['solved']}/{r['runs']}", f"{r['oracle']}/{r['runs']}", r["calls"], r["input"],
            r["cached"], r["output"], per_solved, startup, ",".join(sorted(r["sources"])),
            ",".join(str(c) for c in sorted(r["exit_codes"], key=str)), r["multi_session_runs"],
            ",".join(sorted(r["models"])) or "-", ",".join(sorted(r["requested_models"])) or "-",
        )))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
