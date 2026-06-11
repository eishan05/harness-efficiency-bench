#!/usr/bin/env python3
"""Cross-check the numbers quoted in paper.tex against paper/data.json.

Not a parser: each check encodes one quoted claim. Run after extract_data.py
so a stale figure or sentence fails loudly instead of shipping.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "data.json")))
TEX = open(os.path.join(HERE, "paper.tex")).read()

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def intex(s: str) -> bool:
    return s in TEX


ds, nm = DATA["deepseek"], DATA["nemotron"]
names = DATA["harness_order"]

# Headline spreads
cs_ds = [ds[n]["c_oracle"] for n in names]
cs_nm = [nm[n]["c_oracle"] for n in names]
check("46x spread (DS)", round(max(cs_ds) / min(cs_ds)) == 46)
check("83x spread (NM)", round(max(cs_nm) / min(cs_nm)) == 83)

# Table 1 cells
LABELS = {
    "aider-architect": "Aider (architect)", "aider": "Aider", "claude-code": "Claude Code",
    "codex": "Codex", "goose": "Goose", "hermes-agent": "Hermes", "kilo": "Kilo",
    "kimi-code": "Kimi Code", "nanobot": "Nanobot", "openclaw": "OpenClaw",
    "opencode": "Opencode", "qwen-code": "Qwen Code",
}


def fmt(v: float) -> str:
    return f"{round(v):,}".replace(",", "{,}")


def fmt_turns(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


for n in names:
    row_bits = [fmt(ds[n]["startup_tax"]), fmt(nm[n]["startup_tax"]),
                fmt_turns(ds[n]["turns_median"]),
                fmt(ds[n]["c_oracle"]), fmt(nm[n]["c_oracle"]),
                fmt(ds[n]["c_oracle_disc"]),
                f"{round(ds[n]['cached_share_of_total'] * 100)}\\%",
                str(ds[n]["oracle_solved"]), str(nm[n]["oracle_solved"])]
    row = rf"{re.escape(LABELS[n])}\s*&\s*" + r"\s*&\s*".join(re.escape(b) for b in row_bits)
    check(f"table row {n}", re.search(row, TEX) is not None, " & ".join(row_bits))

# Solved range claim
solved = [g[n]["oracle_solved"] for g in (ds, nm) for n in names]
check("every config solves 11-12", min(solved) == 11 and max(solved) == 12)

# Spearman table
sp = DATA["spearman"]
check("rho A = 1.000 (12)", abs(sp["A"]["rho"] - 1.0) < 5e-4 and sp["A"]["n"] == 12)
check("rho C = 0.993 (12)", abs(sp["C_oracle"]["rho"] - 0.993) < 5e-4 and sp["C_oracle"]["n"] == 12)
check("rho B = 0.673 (10)", abs(sp["B"]["rho"] - 0.673) < 5e-4 and sp["B"]["n"] == 10,
      f"actual {sp['B']['rho']:.3f} n={sp['B']['n']}")
check("rho turns = 0.664 (12)", abs(sp["turns"]["rho"] - 0.664) < 5e-4 and sp["turns"]["n"] == 12,
      f"actual {sp['turns']['rho']:.3f} n={sp['turns']['n']}")
check("tex quotes 0.673", intex("0.673"))
check("tex quotes 0.664", intex("0.664"))
check("tex has no stale 0.627", not intex("0.627"))

# Decomposition
dec = DATA["decomposition"]
check("R2 DS = 0.990", abs(dec["deepseek"]["r2_logC_on_logAT"] - 0.990) < 5e-4)
check("R2 NM = 0.992", abs(dec["nemotron"]["r2_logC_on_logAT"] - 0.992) < 5e-4)
check("spearman C~AT DS = 0.979", abs(dec["deepseek"]["spearman_C_vs_AT"] - 0.979) < 5e-4)
check("spearman C~AT NM = 0.986", abs(dec["nemotron"]["spearman_C_vs_AT"] - 0.986) < 5e-4)
check("tex quotes R2 0.990/0.992", intex("0.990") and intex("0.992"))

# rho(A, C) on DS quoted as 0.951
def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den


rho_ac = spearman([ds[n]["startup_tax"] for n in names], cs_ds)
check("rho(A,C) DS = 0.951", abs(rho_ac - 0.951) < 5e-4, f"actual {rho_ac:.3f}")
check("tex quotes 0.951", intex("0.951"))

# Turn band claim (loopers 6-10 median turns on DS)
loop_meds = [ds[n]["turns_median"] for n in names if n not in ("aider", "aider-architect")]
check("looper turns band 6-10 (DS)", min(loop_meds) >= 6 and max(loop_meds) <= 10,
      f"{min(loop_meds)}-{max(loop_meds)}")

# Cache section numbers
check("codex cached 77%", round(ds["codex"]["cached_share_of_total"] * 100) == 77)
check("codex C 84,794 / disc 26,291",
      round(ds["codex"]["c_oracle"]) == 84794 and round(ds["codex"]["c_oracle_disc"]) == 26291)
check("claude-code disc 51,793", round(ds["claude-code"]["c_oracle_disc"]) == 51793)

# SWE section
swe = DATA["swe"]
check("swe: all resolve only pytest-5227",
      all(v["resolved_tasks"] == ["pytest-dev__pytest-5227"] and v["oracle_solved"] == 1
          for v in swe.values()))
check("swe totals quoted (0.82M/5.27M/12.33M/14.96M)",
      round(swe["aider"]["total_tokens"] / 1e6, 2) == 0.82
      and round(swe["claude-code"]["total_tokens"] / 1e6, 2) == 5.27
      and round(swe["kilo"]["total_tokens"] / 1e6, 2) == 12.33
      and round(swe["codex"]["total_tokens"] / 1e6, 2) == 14.96)
spread = max(v["total_tokens"] for v in swe.values()) / min(v["total_tokens"] for v in swe.values())
check("swe 18x spread", round(spread) == 18, f"actual {spread:.1f}")

# Dcurve: no 200k anywhere in paper-facing claims; levels base..100k
for h, per in DATA["dcurve"].items():
    for lvl in ("base", "20k", "50k", "100k"):
        check(f"dcurve {h} {lvl} attempted 12", per[lvl]["attempted"] == 12)
check("claude-code 2/12 at 100k", DATA["dcurve"]["claude-code"]["100k"]["oracle_solved"] == 2)
check("aider 12/12 at 100k", DATA["dcurve"]["aider"]["100k"]["oracle_solved"] == 12)
check("codex 12/12 at 100k", DATA["dcurve"]["codex"]["100k"]["oracle_solved"] == 12)
check("kilo 12/12 at 100k", DATA["dcurve"]["kilo"]["100k"]["oracle_solved"] == 12)
check("codex 11x at 100k",
      round(DATA["dcurve"]["codex"]["100k"]["mean_tokens"]
            / DATA["dcurve"]["codex"]["base"]["mean_tokens"]) == 11)
check("tex has no 1/12-style 200k claims", "200k level" not in TEX)

# Fidelity: medians quoted in section 4.8 and full-suite coverage
fid = DATA["fidelity"]
for n in names:
    check(f"fidelity {n} runs == 12", fid[n]["runs"] == 12, f"runs={fid[n]['runs']}")
quoted = {
    "aider": 1.03, "aider-architect": 1.01, "codex": 1.11, "goose": 1.07,
    "hermes-agent": 1.05, "nanobot": 1.11, "qwen-code": 1.25,
    "claude-code": 1.05, "kilo": 0.17, "opencode": 0.11,
}
for n, q in quoted.items():
    med = fid[n]["median"]
    check(f"fidelity median {n} ~ {q}", med is not None and abs(med - q) < 0.005,
          f"actual {med}")
check("openclaw zero calls", fid["openclaw"]["median"] == 0.0)
check("kimi-code crash (0.0)", fid["kimi-code"]["median"] == 0.0)

print()
if failures:
    print(f"{len(failures)} check(s) failed")
    sys.exit(1)
print("all checks passed")
