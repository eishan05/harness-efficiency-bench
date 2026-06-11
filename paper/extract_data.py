#!/usr/bin/env python3
"""Extract paper-facing numbers from result snapshots into paper/data.json.

Everything quoted in the paper (tables and figures) is derived from the
canonical snapshots in examples/results/ plus the raw fidelity-probe runs.
"""

from __future__ import annotations

import glob
import json
import os
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "examples", "results")

HARNESSES = [
    ("aider-architect", "aider-docker-openrouter-deepseek-v4-flash-non-swe-score-12-architect-2026-06-09.json", None),
    ("aider", "aider-docker-openrouter-deepseek-v4-flash-non-swe-score-12-2026-06-09.json", None),
    ("claude-code", None, None),
    ("codex", None, None),
    ("goose", None, None),
    ("hermes-agent", None, None),
    ("kilo", None, None),
    ("kimi-code", None, None),
    ("nanobot", None, None),
    ("openclaw", None, None),
    ("opencode", None, None),
    ("qwen-code", None, None),
]


def snapshot_path(name: str, model_tag: str) -> str:
    if name == "aider-architect":
        pats = [f"aider-*{model_tag}*non-swe-score-12*architect*.json",
                f"aider-*{model_tag}*architect*non-swe-score-12*.json"]
    else:
        pats = [f"{name}-*{model_tag}*non-swe-score-12*.json"]
    for pat in pats:
        hits = [p for p in glob.glob(os.path.join(RESULTS, pat))
                if ("architect" in p) == (name == "aider-architect")]
        if hits:
            return hits[0]
    raise FileNotFoundError(f"{name} / {model_tag}")


def load_score12(model_tag: str) -> dict:
    out = {}
    for name, *_ in HARNESSES:
        d = json.load(open(snapshot_path(name, model_tag)))
        s = d["summary"]
        m = s["metrics"]
        tse = m["token_solve_efficiency"]
        usage = s.get("model_usage") or {}
        tot_in = sum(v.get("input_tokens", 0) for v in usage.values())
        total = tse.get("total_token_cost") or 0
        disc_total = tse.get("token_cost_cache_discounted_total")
        # cache-discounted total = total - 0.9 * cached, so invert:
        cached = (total - disc_total) / 0.9 if disc_total is not None else 0.0
        out[name] = {
            "startup_tax": m["startup_tax"].get("avg"),
            "growth": m["context_growth_rate"].get("avg"),
            "c_oracle": tse.get("token_cost_per_oracle_solved_task"),
            "c_oracle_disc": tse.get("token_cost_cache_discounted_per_oracle_solved_task"),
            "total_tokens": tse.get("total_token_cost"),
            "oracle_solved": s.get("oracle_solved"),
            "attempted": s.get("attempted"),
            "cached_tokens": cached,
            "cached_share_of_input": (cached / tot_in) if tot_in else None,
            "cached_share_of_total": (cached / total) if total else 0.0,
            "models_on_wire": sorted(usage.keys()),
        }
    return out


RUN_ROOTS = {
    "deepseek": os.path.join(ROOT, "runs", "openrouter-deepseek-v4-flash-non-swe-score-12-20260609"),
    "nemotron": os.path.join(ROOT, "runs", "openrouter-nemotron-non-swe-score-12-20260609"),
}
ARCH_ROOTS = {
    "deepseek": os.path.join(
        ROOT, "runs",
        "openrouter-deepseek-v4-flash-non-swe-score-12-aider-architect-20260609",
        "aider-docker-openrouter"),
    "nemotron": os.path.join(RUN_ROOTS["nemotron"], "aider-docker-openrouter-architect"),
}


def load_turns(model_tag: str) -> dict:
    """Per-task dominant-model call counts from raw core-grid traces."""
    out = {}
    for name, *_ in HARNESSES:
        if name == "aider-architect":
            root = ARCH_ROOTS[model_tag]
        else:
            root = os.path.join(RUN_ROOTS[model_tag], f"{name}-docker-openrouter")
        per_task = []
        for rp in sorted(glob.glob(os.path.join(root, "results", "*.json"))):
            result = json.load(open(rp))
            trace = result.get("trace_path")
            if not trace or not os.path.exists(os.path.join(ROOT, trace)):
                continue
            tally: dict[str, int] = {}
            calls = []
            for line in open(os.path.join(ROOT, trace)):
                ev = json.loads(line)
                if ev.get("type") != "model_call":
                    continue
                md = ev.get("metadata") or {}
                if md.get("aggregate"):
                    continue
                model = md.get("model") or "?"
                tally[model] = tally.get(model, 0) + (ev.get("input_tokens") or 0)
                calls.append(model)
            task_models = [m for m in tally if not m.startswith("anthropic/")]
            if not task_models:
                continue
            dominant = max(task_models, key=lambda m: tally[m])
            per_task.append(sum(1 for m in calls if m == dominant))
        out[name] = {
            "median": median(per_task) if per_task else None,
            "mean": (sum(per_task) / len(per_task)) if per_task else None,
            "n_tasks": len(per_task),
        }
    return out


def decomposition(grid: dict, turns: dict, names: list[str]) -> dict:
    """OLS of log C on log(A x mean turns), plus the rank correlation."""
    import math

    pts = [(grid[n]["startup_tax"] * turns[n]["mean"], grid[n]["c_oracle"])
           for n in names if turns[n]["mean"]]
    xs = [math.log(a) for a, _ in pts]
    ys = [math.log(c) for _, c in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return {
        "r2_logC_on_logAT": 1 - ss_res / ss_tot,
        "slope": slope,
        "spearman_C_vs_AT": spearman([a for a, _ in pts], [c for _, c in pts]),
        "n": n,
    }


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def load_dcurve() -> dict:
    out = {}
    for p in sorted(glob.glob(os.path.join(RESULTS, "*dcurve-score-12*.json"))):
        d = json.load(open(p))
        name = os.path.basename(p).split("-docker-")[0]
        per = {}
        for run in d["per_run"]:
            per.setdefault(run["perturbation_id"], []).append(run)
        out[name] = {
            pid: {
                "oracle_solved": sum(1 for r in runs if r["oracle_success"]),
                "attempted": len(runs),
                "mean_tokens": sum(r.get("token_cost") or 0 for r in runs) / len(runs),
            }
            for pid, runs in per.items()
        }
    return out


def load_swe() -> dict:
    out = {}
    for p in sorted(glob.glob(os.path.join(RESULTS, "*swe-contrast*.json"))):
        d = json.load(open(p))
        name = os.path.basename(p).split("-docker-")[0]
        s = d["summary"]
        resolved = sorted(r["task_id"] for r in d["per_run"] if r.get("oracle_success"))
        out[name] = {
            "oracle_solved": s["oracle_solved"],
            "attempted": s["attempted"],
            "total_tokens": s["metrics"]["token_solve_efficiency"]["total_token_cost"],
            "resolved_tasks": resolved,
        }
    return out


def load_fidelity() -> dict:
    dcurve = os.path.join(ROOT, "runs", "openrouter-deepseek-v4-flash-dcurve-20260610")
    probe = os.path.join(ROOT, "runs", "openrouter-deepseek-v4-flash-fidelity-100k-20260610")
    configs = {
        "aider": f"{dcurve}/aider-docker-openrouter",
        "aider-architect": f"{probe}/aider-architect",
        "claude-code": f"{dcurve}/claude-code-docker-openrouter",
        "codex": f"{dcurve}/codex-docker-openrouter",
        "goose": f"{probe}/goose",
        "hermes-agent": f"{probe}/hermes-agent",
        "kilo": f"{dcurve}/kilo-docker-openrouter",
        "kimi-code": f"{probe}/kimi-code",
        "nanobot": f"{probe}/nanobot",
        "openclaw": f"{probe}/openclaw",
        "opencode": f"{probe}/opencode",
        "qwen-code": f"{probe}/qwen-code",
    }
    out = {}
    for name, root in configs.items():
        fids, solved, n = [], 0, 0
        for path in sorted(glob.glob(f"{root}/results/*.json")):
            result = json.load(open(path))
            if result.get("perturbation_id") != "100k":
                continue
            prompt = int(result.get("metadata", {}).get("user_prompt_tokens") or 0)
            max_input = 0
            try:
                for line in open(result["trace_path"]):
                    ev = json.loads(line)
                    if ev.get("type") != "model_call" or ev.get("input_tokens") is None:
                        continue
                    if (ev.get("metadata") or {}).get("aggregate"):
                        continue
                    max_input = max(max_input, int(ev["input_tokens"]))
            except FileNotFoundError:
                pass
            fids.append(max_input / prompt if prompt else 0.0)
            solved += 1 if result.get("oracle_result", {}).get("success") else 0
            n += 1
        out[name] = {"median": median(fids) if fids else None,
                     "min": min(fids) if fids else None,
                     "max": max(fids) if fids else None,
                     "runs": n, "oracle_solved": solved}
    return out


def load_pro_100k() -> dict | None:
    """Budget-truncated Claude Code 100k probe on DeepSeek V4 Pro."""
    root = os.path.join(ROOT, "runs",
                        "openrouter-deepseek-v4-pro-claude-code-100k-20260611",
                        "claude-code-docker-openrouter")
    paths = sorted(glob.glob(os.path.join(root, "results", "*.json")))
    if not paths:
        return None
    attempted = solved = 0
    calls_per_run, max_inputs = [], []
    for rp in paths:
        result = json.load(open(rp))
        attempted += 1
        solved += 1 if (result.get("oracle_result") or {}).get("success") else 0
        n, mx = 0, 0
        try:
            for line in open(result["trace_path"]):
                ev = json.loads(line)
                if ev.get("type") != "model_call" or (ev.get("metadata") or {}).get("aggregate"):
                    continue
                n += 1
                mx = max(mx, ev.get("input_tokens") or 0)
        except (FileNotFoundError, KeyError):
            pass
        calls_per_run.append(n)
        max_inputs.append(mx)
    return {"attempted": attempted, "oracle_solved": solved,
            "median_calls": median(calls_per_run),
            "median_max_input": median(max_inputs)}


def main() -> None:
    deepseek = load_score12("deepseek-v4-flash")
    nemotron = load_score12("nemotron")
    names = [h[0] for h in HARNESSES]

    def rho_for(key, exclude=()):
        pairs = [(deepseek[n][key], nemotron[n][key]) for n in names
                 if n not in exclude
                 and deepseek[n][key] is not None and nemotron[n][key] is not None]
        return {"rho": spearman([p[0] for p in pairs], [p[1] for p in pairs]),
                "n": len(pairs)}

    # aider-architect's two-call runs give a slope through two points, not a
    # growth rate; exclude it from B's cross-model comparison.
    rho = {"A": rho_for("startup_tax"),
           "B": rho_for("growth", exclude=("aider-architect",)),
           "C_oracle": rho_for("c_oracle")}
    turns = {"deepseek": load_turns("deepseek"), "nemotron": load_turns("nemotron")}
    for tag, grid in (("deepseek", deepseek), ("nemotron", nemotron)):
        for n in names:
            grid[n]["turns_median"] = turns[tag][n]["median"]
            grid[n]["turns_mean"] = turns[tag][n]["mean"]
    rho["turns"] = {
        "rho": spearman([turns["deepseek"][n]["mean"] for n in names],
                        [turns["nemotron"][n]["mean"] for n in names]),
        "n": len(names),
    }
    data = {
        "harness_order": names,
        "deepseek": deepseek,
        "nemotron": nemotron,
        "spearman": rho,
        "decomposition": {tag: decomposition(grid, turns[tag], names)
                          for tag, grid in (("deepseek", deepseek), ("nemotron", nemotron))},
        "dcurve": load_dcurve(),
        "swe": load_swe(),
        "fidelity": load_fidelity(),
        "pro_100k_claude_code": load_pro_100k(),
    }
    out = os.path.join(ROOT, "paper", "data.json")
    json.dump(data, open(out, "w"), indent=1, sort_keys=True)
    print(f"wrote {out}")
    print("spearman:", rho)


if __name__ == "__main__":
    main()
