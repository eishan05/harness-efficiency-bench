#!/usr/bin/env python3
"""Generate all paper figures (PDF) from paper/data.json."""

from __future__ import annotations

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "data.json")))
FIGDIR = os.path.join(HERE, "figures")
os.makedirs(FIGDIR, exist_ok=True)

plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 9,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "figure.dpi": 150,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

LABELS = {
    "aider-architect": "Aider (architect)",
    "aider": "Aider",
    "claude-code": "Claude Code",
    "codex": "Codex",
    "goose": "Goose",
    "hermes-agent": "Hermes",
    "kilo": "Kilo",
    "kimi-code": "Kimi Code",
    "nanobot": "Nanobot",
    "openclaw": "OpenClaw",
    "opencode": "Opencode",
    "qwen-code": "Qwen Code",
}

C_DS = "#1f6f8b"   # deepseek
C_NM = "#e08a3c"   # nemotron
C_RAW = "#9aa5b1"
C_DISC = "#1f6f8b"

order_by_c = sorted(DATA["harness_order"], key=lambda n: DATA["deepseek"][n]["c_oracle"])


def save(fig, name):
    fig.savefig(os.path.join(FIGDIR, name), bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def fig_cost():
    names = order_by_c
    y = np.arange(len(names))
    ds = [DATA["deepseek"][n]["c_oracle"] for n in names]
    nm = [DATA["nemotron"][n]["c_oracle"] for n in names]
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    h = 0.38
    ax.barh(y + h / 2, ds, height=h, color=C_DS, label="DeepSeek V4 Flash")
    ax.barh(y - h / 2, nm, height=h, color=C_NM, label="Nemotron 3 Ultra")
    ax.set_yticks(y, [LABELS[n] for n in names])
    ax.set_xscale("log")
    ax.set_xlabel("Tokens per oracle-solved task (log scale)")
    ax.invert_yaxis()
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="x", alpha=0.3, linewidth=0.5)
    save(fig, "fig_cost.pdf")


def fig_startup():
    names = DATA["harness_order"]
    ds = np.array([DATA["deepseek"][n]["startup_tax"] for n in names])
    nm = np.array([DATA["nemotron"][n]["startup_tax"] for n in names])
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    lim = [500, 40000]
    ax.plot(lim, lim, color="#bbbbbb", linewidth=0.8, zorder=1)
    ax.scatter(ds, nm, s=22, color=C_DS, zorder=2)
    for n, x, yv in zip(names, ds, nm):
        if n in ("aider-architect", "openclaw", "kilo", "qwen-code", "codex"):
            ax.annotate(LABELS[n], (x, yv), textcoords="offset points",
                        xytext=(5, -2), fontsize=7, color="#444444")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("Startup tax, DeepSeek V4 Flash (tokens)")
    ax.set_ylabel("Startup tax, Nemotron 3 Ultra (tokens)")
    ax.grid(alpha=0.3, linewidth=0.5)
    save(fig, "fig_startup.pdf")


def fig_cache():
    names = [n for n in order_by_c if DATA["deepseek"][n]["cached_tokens"] > 1000]
    y = np.arange(len(names))
    raw = [DATA["deepseek"][n]["c_oracle"] for n in names]
    disc = [DATA["deepseek"][n]["c_oracle_disc"] for n in names]
    fig, ax = plt.subplots(figsize=(4.8, 2.8))
    h = 0.38
    ax.barh(y + h / 2, raw, height=h, color=C_RAW, label="Raw tokens")
    ax.barh(y - h / 2, disc, height=h, color=C_DISC,
            label="Cache-discounted (cache reads at 0.1$\\times$)")
    ax.set_yticks(y, [LABELS[n] for n in names])
    ax.set_xlabel("Tokens per oracle-solved task (DeepSeek V4 Flash)")
    ax.invert_yaxis()
    ax.legend(loc="upper right", frameon=False)
    ax.grid(axis="x", alpha=0.3, linewidth=0.5)
    save(fig, "fig_cache.pdf")


def fig_dcurve():
    levels = ["base", "20k", "50k", "100k"]
    xs = [0, 20, 50, 100]
    colors = {"aider": "#1f6f8b", "claude-code": "#c0504d",
              "codex": "#5b9244", "kilo": "#8064a2"}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.6, 2.7))
    for h, per in DATA["dcurve"].items():
        rate = [per[l]["oracle_solved"] / per[l]["attempted"] for l in levels]
        ax1.plot(xs, rate, marker="o", markersize=3.5, color=colors[h],
                 label=LABELS[h], linewidth=1.4)
        toks, txs = [], []
        for l, x in zip(levels, xs):
            t = per[l]["mean_tokens"]
            if t > 0:
                toks.append(t)
                txs.append(x)
        ax2.plot(txs, toks, marker="o", markersize=3.5, color=colors[h],
                 linewidth=1.4)
    ax1.set_xlabel("Injected irrelevant context ($10^3$ tokens)")
    ax1.set_ylabel("Oracle solve rate (12 tasks)")
    ax1.set_ylim(-0.05, 1.08)
    ax1.legend(frameon=False, loc="center left", fontsize=7)
    ax1.grid(alpha=0.3, linewidth=0.5)
    ax2.set_xlabel("Injected irrelevant context ($10^3$ tokens)")
    ax2.set_ylabel("Mean tokens per task")
    ax2.set_yscale("log")
    ax2.grid(alpha=0.3, linewidth=0.5)
    fig.tight_layout()
    save(fig, "fig_dcurve.pdf")


def fig_fidelity():
    names = DATA["harness_order"]
    fid = DATA["fidelity"]
    order = sorted(names, key=lambda n: -(fid[n]["median"] or 0))
    med = [fid[n]["median"] for n in order]
    cls = []
    for n in order:
        m = fid[n]["median"]
        solved = fid[n]["oracle_solved"]
        runs = fid[n]["runs"]
        if m >= 0.9 and solved / runs >= 0.5:
            cls.append(("faithful", "#1f6f8b"))
        elif m >= 0.9:
            cls.append(("faithful, fails task", "#c0504d"))
        elif m > 0.02:
            cls.append(("silent truncation", "#e08a3c"))
        else:
            cls.append(("refusal / crash", "#7f7f7f"))
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(4.8, 3.0))
    ax.barh(y, med, height=0.62, color=[c for _, c in cls])
    for i, n in enumerate(order):
        if (fid[n]["median"] or 0) < 0.02:
            note = "refused to run" if n == "openclaw" else "crashed"
            ax.text(0.02, i, f"0.00 ({note})", va="center", fontsize=7,
                    color="#555555")
    ax.axvline(1.0, color="#444444", linewidth=0.8, linestyle="--")
    ax.set_yticks(y, [LABELS[n] for n in order])
    ax.set_xlabel("Transmission fidelity at 100k injected tokens\n"
                  "(max model-call input $\\div$ rendered prompt)")
    ax.invert_yaxis()
    seen = {}
    for label, color in cls:
        seen.setdefault(label, color)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in seen.values()]
    ax.legend(handles, seen.keys(), frameon=False, loc="lower right", fontsize=7)
    ax.grid(axis="x", alpha=0.3, linewidth=0.5)
    save(fig, "fig_fidelity.pdf")


def fig_swe():
    names = sorted(DATA["swe"], key=lambda n: DATA["swe"][n]["total_tokens"])
    y = np.arange(len(names))
    toks = [DATA["swe"][n]["total_tokens"] / 1e6 for n in names]
    fig, ax = plt.subplots(figsize=(4.6, 1.9))
    ax.barh(y, toks, height=0.6, color=C_DS)
    for i, (n, t) in enumerate(zip(names, toks)):
        ax.text(t + 0.18, i, f"{t:.1f}M, 1/10 resolved", va="center", fontsize=7.5,
                color="#333333")
    ax.set_yticks(y, [LABELS[n] for n in names])
    ax.set_xlabel("Total tokens on 10 SWE-bench Lite tasks (millions)")
    ax.set_xlim(0, 19.5)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3, linewidth=0.5)
    save(fig, "fig_swe.pdf")


fig_cost()
fig_startup()
fig_cache()
fig_dcurve()
fig_fidelity()
fig_swe()
