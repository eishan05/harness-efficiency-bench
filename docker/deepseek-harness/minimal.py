#!/usr/bin/env python3
"""Run one task on dsh's sdk-minimal profile through the Python SDK.

Mirrors the repo's python/sdk/examples/minimal.py, which its BENCHMARK.md names as
the benchmark entry point: persistent bash + read_image, a one-line system prompt.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from deepseek_harness import DeepSeekHarness


def main() -> int:
    prompt = Path(sys.argv[1]).read_text(encoding="utf-8")
    max_tokens = os.environ.get("BENCH_MAX_OUTPUT_TOKENS")
    with DeepSeekHarness(
        provider="deepseek-official",
        model=os.environ["BENCH_MODEL"],
        max_tokens=int(max_tokens) if max_tokens else None,
        cwd=str(Path.cwd().resolve()),
        dsh_home=os.environ["DSH_HOME"],
        profile="sdk-minimal",
        patches=("/opt/harness/bench.patch.yml",),
    ) as harness:
        result = harness.run(prompt, session_id="bench")
    print(result.final_response)
    if result.finish_reason not in (None, "completed"):
        print(f"dsh: finished with {result.finish_reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
