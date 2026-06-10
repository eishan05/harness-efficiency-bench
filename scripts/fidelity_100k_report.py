#!/usr/bin/env python3
"""Transmission-fidelity report for 100k injected-context runs.

Fidelity = (max model-call input tokens in the run) / (rendered prompt tokens).
~1.0 means the harness transmitted the payload; far below 1.0 means it was
truncated or never sent. Reads the D-curve roots for the four contrast
harnesses and the fidelity-probe roots for the rest."""

from __future__ import annotations

import glob
import json
from statistics import median

DCURVE = "runs/openrouter-deepseek-v4-flash-dcurve-20260610"
PROBE = "runs/openrouter-deepseek-v4-flash-fidelity-100k-20260610"

CONFIGS = [
    ("aider", f"{DCURVE}/aider-docker-openrouter"),
    ("aider-architect", f"{PROBE}/aider-architect"),
    ("claude-code", f"{DCURVE}/claude-code-docker-openrouter"),
    ("codex", f"{DCURVE}/codex-docker-openrouter"),
    ("goose", f"{PROBE}/goose"),
    ("hermes-agent", f"{PROBE}/hermes-agent"),
    ("kilo", f"{DCURVE}/kilo-docker-openrouter"),
    ("kimi-code", f"{PROBE}/kimi-code"),
    ("nanobot", f"{PROBE}/nanobot"),
    ("openclaw", f"{PROBE}/openclaw"),
    ("opencode", f"{PROBE}/opencode"),
    ("qwen-code", f"{PROBE}/qwen-code"),
]


def run_fidelity(result: dict) -> tuple[float, bool]:
    prompt = int(result.get("metadata", {}).get("user_prompt_tokens") or 0)
    max_input = 0
    try:
        for line in open(result["trace_path"]):
            event = json.loads(line)
            if event.get("type") != "model_call" or event.get("input_tokens") is None:
                continue
            if (event.get("metadata") or {}).get("aggregate"):
                continue
            max_input = max(max_input, int(event["input_tokens"]))
    except FileNotFoundError:
        pass
    solved = bool(result.get("oracle_result", {}).get("success"))
    return (max_input / prompt if prompt else 0.0), solved


def main() -> int:
    print(f"{'config':16} {'runs':>4} {'fidelity med':>12} {'min':>6} {'max':>6} {'oracle':>7}")
    for name, root in CONFIGS:
        fidelities: list[float] = []
        solved = 0
        for path in sorted(glob.glob(f"{root}/results/*.json")):
            result = json.load(open(path))
            if result.get("perturbation_id") != "100k":
                continue
            fid, ok = run_fidelity(result)
            fidelities.append(fid)
            solved += 1 if ok else 0
        if not fidelities:
            print(f"{name:16}    0  no 100k runs found")
            continue
        print(
            f"{name:16} {len(fidelities):>4} {median(fidelities):>12.2f} "
            f"{min(fidelities):>6.2f} {max(fidelities):>6.2f} {solved:>3}/{len(fidelities)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
