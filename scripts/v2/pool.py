#!/usr/bin/env python3
"""Pool repeated v2 runs: median and range of tokens per solved task per harness.

    python3 scripts/v2/pool.py runs/v2/r1 runs/v2/r2 runs/v2/r3 [--csv out.csv]

Per harness and run: graded-pass solves, tokens per graded-pass solve (token_cost /
solves), cache-discounted tokens per solve (cached input weighted 0.1), mean startup
tax, and list cost in USD. Across runs: median, min and max of tokens per solve,
total solves, median startup tax, cached share of input.

Cache columns come from the per-call proxy records in traces/*.jsonl:
- calls 2+: cached share of input after each task's first call (the first call
  cannot reuse anything from its own task);
- first call: cached share of each task's first call (reuse across tasks);
- prefix reuse: median of (next call's cached tokens / previous call's input), over
  calls with at least 1024 input tokens; near 100% means the harness keeps its prompt
  prefix stable from turn to turn.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path


def proxy_calls(trace: Path) -> list[dict]:
    calls = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "model_call" and (event.get("metadata") or {}).get("source") == "usage_proxy":
            calls.append(event)
    calls.sort(key=lambda c: (c["metadata"].get("request_started_at") or "", c.get("call_index", 0)))
    return calls


def cache_stats(folder: Path) -> dict:
    later_input = later_cached = first_input = first_cached = 0
    reuse = []
    for trace in sorted((folder / "traces").glob("*.jsonl")):
        calls = proxy_calls(trace)
        if not calls:
            continue
        first_input += calls[0]["input_tokens"]
        first_cached += calls[0]["cached_input_tokens"]
        for call in calls[1:]:
            later_input += call["input_tokens"]
            later_cached += call["cached_input_tokens"]
        for previous, current in zip(calls, calls[1:]):
            if previous["input_tokens"] >= 1024:
                reuse.append(min(current["cached_input_tokens"] / previous["input_tokens"], 1.0))
    return {"later_input": later_input, "later_cached": later_cached,
            "first_input": first_input, "first_cached": first_cached, "reuse": reuse}


def run_stats(folder: Path) -> dict | None:
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "results").glob("*.json"))]
    if not results:
        return None
    solved = sum(1 for r in results if (r.get("oracle_result") or {}).get("success"))
    usage = [((r.get("metrics") or {}).get("usage") or {}) for r in results]
    tokens = sum(int(u.get("token_cost") or 0) for u in usage)
    discounted = sum(float(u.get("token_cost_cache_discounted") or 0) for u in usage)
    input_tokens = sum(int(u.get("input_tokens") or 0) for u in usage)
    cached = sum(int(u.get("cached_input_tokens") or 0) for u in usage)
    taxes = [((r.get("metrics") or {}).get("startup_tax") or {}).get("value") for r in results]
    taxes = [t for t in taxes if t is not None]
    return {
        "attempted": len(results),
        "solved": solved,
        "tokens_per_solved": tokens / solved if solved else None,
        "discounted_per_solved": discounted / solved if solved else None,
        "startup_tax": statistics.mean(taxes) if taxes else None,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cost_usd": sum(float(u.get("cost_usd") or 0) for u in usage),
        **cache_stats(folder),
    }


def main() -> int:
    args = sys.argv[1:]
    out_csv = None
    if "--csv" in args:
        index = args.index("--csv")
        out_csv = Path(args[index + 1])
        del args[index : index + 2]
    runs = [Path(a) for a in args]
    if not runs:
        print(__doc__, file=sys.stderr)
        return 2
    harnesses = sorted({d.name for run in runs for d in run.iterdir() if (d / "results").is_dir()})
    rows = []
    for harness in harnesses:
        stats = [s for s in (run_stats(run / harness) for run in runs if (run / harness).is_dir()) if s]
        per_solved = [s["tokens_per_solved"] for s in stats if s["tokens_per_solved"] is not None]
        discounted = [s["discounted_per_solved"] for s in stats if s["discounted_per_solved"] is not None]
        taxes = [s["startup_tax"] for s in stats if s["startup_tax"] is not None]
        input_tokens = sum(s["input_tokens"] for s in stats)
        later_input = sum(s["later_input"] for s in stats)
        first_input = sum(s["first_input"] for s in stats)
        reuse = [x for s in stats for x in s["reuse"]]
        rows.append({
            "harness": harness,
            "runs": len(stats),
            "solved": sum(s["solved"] for s in stats),
            "attempted": sum(s["attempted"] for s in stats),
            "tokens_per_solved_median": round(statistics.median(per_solved)) if per_solved else None,
            "tokens_per_solved_min": round(min(per_solved)) if per_solved else None,
            "tokens_per_solved_max": round(max(per_solved)) if per_solved else None,
            "discounted_per_solved_median": round(statistics.median(discounted)) if discounted else None,
            "startup_tax_median": round(statistics.median(taxes)) if taxes else None,
            "cached_share": round(sum(s["cached_input_tokens"] for s in stats) / input_tokens, 3) if input_tokens else None,
            "cached_share_calls_2plus": round(sum(s["later_cached"] for s in stats) / later_input, 3) if later_input else None,
            "cached_share_first_call": round(sum(s["first_cached"] for s in stats) / first_input, 3) if first_input else None,
            "prefix_reuse_median": round(statistics.median(reuse), 3) if reuse else None,
            "cost_usd": round(sum(s["cost_usd"] for s in stats), 4),
        })
    rows.sort(key=lambda r: (r["tokens_per_solved_median"] is None, r["tokens_per_solved_median"] or 0))
    header = ["harness", "solved", "tok/solved median", "min-max", "cache-discounted median",
              "startup median", "cached share", "cached 2+", "cached 1st call", "prefix reuse", "list $"]
    print(" | ".join(header))
    print(" | ".join("---" for _ in header))
    for r in rows:
        print(" | ".join(str(x) for x in (
            r["harness"], f"{r['solved']}/{r['attempted']}", r["tokens_per_solved_median"],
            f"{r['tokens_per_solved_min']}-{r['tokens_per_solved_max']}", r["discounted_per_solved_median"],
            r["startup_tax_median"], r["cached_share"], r["cached_share_calls_2plus"],
            r["cached_share_first_call"], r["prefix_reuse_median"], r["cost_usd"],
        )))
    if out_csv:
        with out_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
