# Saved Benchmark Results

These compact snapshots preserve benchmark metrics without keeping the large raw traces in git. The citable A/B/C comparison sets are the two score-12 batches below; the SWE-bench Lite snapshots are telemetry diagnostics, not solve-rate claims.

## Non-SWE score-12 batches

Each batch runs the 12 score-facing non-SWE tasks (`--include-tag score-facing`) once per harness configuration, Docker-isolated, via OpenRouter with the usage proxy capturing per-call tokens. Twelve configurations per batch: eleven harnesses plus Aider in `AIDER_ARCHITECT=1` mode. Metrics are recomputed from raw traces with the current metric rules (auxiliary-preflight and model-mismatch helper detection, monotone-thread segmentation, cumulative-summary exclusion, strict and oracle C denominators, cache-discounted C; see `docs/metric-coverage.md`).

### DeepSeek V4 Flash (2026-06-09)

`*-deepseek-v4-flash-non-swe-score-12-2026-06-09.json`, model `deepseek/deepseek-v4-flash`. Notable per-harness facts:

- Opencode and Kilo send a per-task helper request billed to `anthropic/claude-4.5-haiku` (8.2k and 16.4k input tokens per batch respectively, disclosed in each snapshot's `model_usage`), so the "same model across harnesses" control leaks a small amount of Haiku traffic for those two CLIs. Helper calls are excluded from task-first startup tax and the context-growth fit but kept in solve-efficiency totals.
- Qwen Code's native stream ends with a `result` event repeating the cumulative session usage; it is excluded structurally. Counting it had doubled Qwen's C (4.36M → 2.18M) and faked a ~11.5k/turn growth slope; corrected averages are A ≈ 21.4k, B ≈ 452.
- Kilo passed all 12 oracles but 5 runs exited through the wrapper wall-time cap, so its strict C is 204.5k while its oracle C is 119.3k tokens per solved task.
- Cache-discounted C (cached input at 0.1 weight) reorders the expensive end: Codex drops from 1.02M to 315k total tokens and Kilo from 1.43M to 589k, while Claude Code's proxy reports near-zero cached tokens and barely moves.

### NVIDIA Nemotron 3 Ultra free (2026-06-10)

`*-nemotron-non-swe-score-12-2026-06-10.json`, model `nvidia/nemotron-3-ultra-550b-a55b:free`, same protocol (driver: `scripts/run_nemotron_score12_batch.sh`). Oracle solve rates are 11-12/12 for every configuration. The free endpoint reports zero cached input tokens, so cache-discounted C equals raw C in this batch; cache effects are only measurable on the DeepSeek batch. The Opencode/Kilo Haiku helper leakage reproduces to the token (8,170 and 16,366 input tokens), and plain Aider again makes one model call per task, leaving its B unsupported.

### SWE-bench contrast run (2026-06-10)

`{aider,claude-code,codex,kilo}-docker-openrouter-deepseek-v4-flash-swe-contrast-curated-10-2026-06-10.json`: four harnesses spanning the cost spectrum over the 10 curated SWE-bench Lite tasks on `deepseek/deepseek-v4-flash` with generous bounds (aider: architect + repo-map 2048 + 900s wall; claude-code: `CLAUDE_MAX_BUDGET_USD=5`; codex: 1800s task cap; kilo: 900s wall), graded inline by the ARM-local Docker SWE-bench oracle. All four resolved exactly the same single instance (`pytest-dev__pytest-5227`) — 1/10 each — while spending 0.82M (aider), 5.27M (claude-code), 12.33M (kilo), and 14.96M (codex) tokens. An 18x token spread bought identical outcomes; with this model the capability ceiling is the model, not the scaffolding. Raising claude-code's budget from $1 to $5 (3.3x more tokens than its earlier budget-capped run, 9/10 non-empty diffs vs 1/10) added zero resolved instances.

### Context-bloat harm curve (D metric, 2026-06-10)

`{aider,claude-code,codex,kilo}-docker-openrouter-deepseek-v4-flash-dcurve-score-12-2026-06-10.json`: the same four harnesses over the 12 score-facing tasks at base/20k/50k/100k injected-context levels (`--all-perturbations`, task timeout overridden to 900s via `--task-timeout-sec`). Oracle solves and average tokens per run:

| Harness | base | 20k | 50k | 100k | 100k payload transmitted? |
|---|---|---|---|---|---|
| aider | 12/12, 5k | 11/12, 25k | 12/12, 55k | 12/12, 106k | yes (~103k, one call) |
| claude-code | 12/12, 47k | 12/12, 222k | 12/12, 473k | **2/12**, 287k | yes (~100k every call) |
| codex | 12/12, 82k | 12/12, 237k | 12/12, 480k | 12/12, 909k | yes (~108k every call) |
| kilo | 12/12, 119k | 12/12, 123k | 12/12, 125k | 12/12, 126k | **no (~13.5k; payload silently dropped)** |

The model itself does not degrade at these context sizes (aider passes the full payload in one shot and stays perfect). Claude Code transmits faithfully and collapses at 100k: runs end after 2-3 calls with no edits — its final call sees ~33k input by its own accounting, consistent with compaction/truncation losing the task instruction buried after the payload. Codex transmits faithfully and stays robust but pays payload × turns (11x its base cost at 100k). Kilo's flat curve and flat cost are explained by it truncating the rendered prompt before sending — robustness by silently discarding user-provided context. Kilo's strict counts (5-8/12 per level) reflect 900s wall-cap exits, evenly spread across levels; its oracle solve is 49/49. The single 200k probe (`toy-write-file`) fails for the faithful harnesses at the model's 200k window, as expected.

### 100k transmission-fidelity probe (2026-06-10)

All 12 configurations were probed at the 100k injected-context level (the four contrast harnesses via their D-curve runs; the rest via three-task probes under `runs/openrouter-deepseek-v4-flash-fidelity-100k-20260610/`, identical harness config, 900s timeout). Fidelity = max model-call input tokens / rendered prompt tokens (`scripts/fidelity_100k_report.py`):

| Behavior | Configs (median fidelity) |
|---|---|
| Faithful, robust | aider (1.03), aider-architect (1.01), codex (1.11), goose (1.06), hermes-agent (1.05), nanobot (1.10), qwen-code (1.23) |
| Faithful, collapses | claude-code (1.05; 2/12 solved at 100k) |
| Silent truncation | kilo (0.17), opencode (0.10) — both solve anyway, having dropped ~85-90% of the input |
| Loud refusal | openclaw (0.00) — window-overflow precheck, zero model calls, clear error, exit 0 |
| Hard crash | kimi-code (0.00) — unhandled `compaction.unable` Node exception, zero tokens |

Notably the two silent truncators are the same two CLIs that route helper calls to Claude Haiku. None of this is visible from agent output alone; it requires network-level token counting.

### Cross-model rank agreement

Spearman rank correlation between the two batches across the 12 configurations:

| Metric | rho | Reading |
|---|---:|---|
| A (startup tax avg) | 1.000 | Identical ranking on both models; startup tax is a harness-intrinsic constant. |
| C (tokens per oracle-solved task) | 0.993 | One adjacent swap (nanobot/opencode); the efficiency ordering is robust across models. |
| B (context growth avg, 11 configs) | 0.627 | The few-hundred-tokens-per-turn band replicates, but ranks inside the band shuffle; fine-grained B orderings are not defensible from single runs. |

## Codex SWE-bench Lite

- `codex-local-swe-bench-lite-curated-10-smoke-2026-06-08.json`: local subscription Codex no-oracle smoke over the 10 curated SWE-bench Lite tasks.
- `codex-docker-openrouter-nvidia-swe-bench-lite-curated-10-regrade-2026-06-08.json`: the Codex Docker OpenRouter SWE-bench Lite subset regraded from saved patches with the fixed Docker SWE-bench oracle environment. On this ARM host, the regrade uses local ARM SWE-bench images instead of the official amd64 remote images. The saved A/B/C token metrics come from the original Codex traces; correctness comes from the external regrade report. One patch is oracle-resolved, but the strict benchmark solved count remains 0 because that original Codex adapter run timed out.

## Docker OpenRouter calibration and SWE-bench Lite diagnostics

- `openrouter-docker-smoke-calibration-2026-06-08.json`: two-task Docker smoke over the measurable OpenRouter harnesses using `toy-write-file` and `metrics-calibration-multicall`. It combines the main smoke run with patched Goose and OpenClaw reruns, and excludes Antigravity CLI and Grok Build because those CLIs are not currently full A/B/C candidates.
- `aider-docker-openrouter-nvidia-swe-bench-lite-first-architect-map0-2026-06-09.json`: first-task Aider SWE-bench Lite diagnostic with `AIDER_ARCHITECT=1` and `AIDER_MAP_TOKENS=0`. A/B/C are full, but the patch was empty because Aider had no repo-map or positional file context. Attempts with `AIDER_MAP_TOKENS=512` and `2048` stalled on in-flight OpenRouter free-model requests before usage was returned; later bounded diagnostics can use `AIDER_MAX_WALL_TIME`, but reliable Aider SWE B coverage still depends on getting at least two completed provider calls.
- `aider-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-architect-map0-2026-06-09.json`: Docker-isolated Aider over the 10 curated SWE-bench Lite tasks with `AIDER_MAX_WALL_TIME=90s`, `AIDER_ARCHITECT=1`, `AIDER_MAP_TOKENS=0`, and `AIDER_FILE_MODE=repo-map`. This is a telemetry diagnostic, not a representative Aider solve configuration: A startup tax and C token solve efficiency are full for all 10 runs, while B context growth is partial because five runs made only one completed model call. The strict and ARM-local Docker SWE-bench oracle solved counts are both 0/10.
- `claude-code-docker-openrouter-nvidia-swe-bench-lite-first-budget-2026-06-09.json`: first-task Claude Code SWE-bench Lite diagnostic. A/B/C are full, but the run hit Claude Code's default `--max-budget-usd 1.00` guard after about 204k tokens before producing a patch, so the SWE oracle saw an empty patch. The Docker Claude manifests now allow `CLAUDE_MAX_BUDGET_USD` to raise this guard for longer runs.
- `claude-code-docker-openrouter-nvidia-swe-bench-lite-curated-10-budget020-2026-06-09.json`: Docker-isolated Claude Code over the 10 curated SWE-bench Lite tasks with `CLAUDE_MAX_BUDGET_USD=0.20`. A/B/C are full for all 10 runs. The strict benchmark solved count is 0/10 because Claude Code exited nonzero on each budget-bounded run, while the SWE-bench oracle resolved 1/10 patches.
- `goose-docker-openrouter-nvidia-swe-bench-lite-curated-10-bounded-2026-06-09.json`: Docker-isolated Goose via OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`, covering the 10 curated SWE-bench Lite tasks with `GOOSE_MAX_TURNS=12`. It solved 1/10 with the ARM-local Docker SWE-bench oracle; A startup tax and C token solve efficiency are full, while B context growth is partial because one run had insufficient per-call points.
- `hermes-agent-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task Hermes Agent SWE-bench Lite diagnostic. A/B/C are full, but the agent made 22 measured model calls and used about 0.25M tokens before being manually stopped after it produced a partial patch and continued making model calls. The patch was unresolved; later runs use `HERMES_MAX_WALL_TIME` for repeatable unattended SWE diagnostics.
- `hermes-agent-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-2026-06-09.json`: Docker-isolated Hermes Agent over the 10 curated SWE-bench Lite tasks with `HERMES_MAX_WALL_TIME=90s`. A startup tax and C token solve efficiency are full for all 10 runs, while B context growth is partial because two exit-code-0 failures made only one model call. The strict benchmark solved count is 0/10, while the SWE-bench oracle resolved 1/10 patches.
- `kilo-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task Kilo SWE-bench Lite diagnostic. A/B/C are full, but the agent made 30 model calls and used about 1.03M tokens before being manually stopped so the partial patch could be graded. The patch was unresolved; later runs use `KILO_MAX_WALL_TIME` for repeatable unattended SWE diagnostics.
- `kilo-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-2026-06-09.json`: Docker-isolated Kilo over the 10 curated SWE-bench Lite tasks with `KILO_MAX_WALL_TIME=90s`. A/B/C are full for all 10 runs. It solved 1/10 strictly and with the ARM-local Docker SWE-bench oracle; 8 runs exited through the wrapper timeout cap and one additional exit-code-0 run was oracle-unresolved.
- `kimi-code-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task Kimi Code SWE-bench Lite diagnostic. A/B/C are full, but the agent made 35 model calls and used about 1.63M tokens before being manually stopped so the partial patch could be graded. The patch was empty and unresolved; later runs use `KIMI_MAX_WALL_TIME` for repeatable unattended SWE diagnostics.
- `kimi-code-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-2026-06-09.json`: Docker-isolated Kimi Code over the 10 curated SWE-bench Lite tasks with `KIMI_MAX_WALL_TIME=90s`. A/B/C are full for all 10 runs. The strict benchmark solved count is 0/10 because every run exited through the wrapper timeout cap, while the SWE-bench oracle resolved 1/10 patches.
- `nanobot-docker-openrouter-nvidia-swe-bench-lite-curated-10-partial-2026-06-08.json`: partial Nanobot SWE-bench Lite diagnostic. The first task hit the 1800-second task timeout after 153 agent iterations, so the full suite was stopped before spending hours on the remaining tasks.
- `nanobot-docker-openrouter-nvidia-swe-bench-lite-first-bounded-2026-06-09.json`: first-task Nanobot SWE-bench Lite diagnostic bounded with `NANOBOT_MAX_TOOL_ITERATIONS=12`. A/B/C are full; the run made 12 measured model calls, used 150,530 total tokens, produced an unresolved patch, and exited before the earlier 1800-second timeout path.
- `nanobot-docker-openrouter-nvidia-swe-bench-lite-curated-10-bounded-2026-06-09.json`: Docker-isolated Nanobot over the 10 curated SWE-bench Lite tasks, bounded with `NANOBOT_MAX_TOOL_ITERATIONS=12`. It solved 1/10 with the ARM-local Docker SWE-bench oracle; A startup tax and C token solve efficiency are full, while B context growth is partial because one run made only one model call.
- `openclaw-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task OpenClaw SWE-bench Lite diagnostic. A/B/C are full, but the agent made 15 measured model calls and used about 0.63M tokens before being manually stopped after context growth and a provider timeout. The submitted diff included OpenClaw workspace metadata and was unresolved; later unattended SWE diagnostics can use `OPENCLAW_MAX_WALL_TIME` and `OPENCLAW_TIMEOUT_SEC`.
- `openclaw-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-2026-06-09.json`: Docker-isolated OpenClaw over the 10 curated SWE-bench Lite tasks with `OPENCLAW_MAX_WALL_TIME=90s` and `OPENCLAW_TIMEOUT_SEC=85`. A startup tax and C token solve efficiency are full for all 10 runs, while B context growth is partial because five runs made only one completed model call. The strict benchmark solved count is 0/10, while the ARM-local Docker SWE-bench oracle resolved 1/10 patches.
- `opencode-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task Opencode SWE-bench Lite diagnostic. A/B/C are full, but the agent made 72 model calls and used about 3.0M tokens before being manually stopped so the partial patch could be graded. The patch was unresolved; later runs use `OPENCODE_MAX_WALL_TIME` for repeatable unattended SWE diagnostics.
- `opencode-docker-openrouter-nvidia-swe-bench-lite-curated-10-wall90-2026-06-09.json`: Docker-isolated Opencode over the 10 curated SWE-bench Lite tasks with `OPENCODE_MAX_WALL_TIME=90s`. A/B/C are full for all 10 runs. It solved 1/10 strictly and with the ARM-local Docker SWE-bench oracle; the other 9 runs exited through the wrapper timeout cap.
- `qwen-code-docker-openrouter-nvidia-swe-bench-lite-first-stopped-2026-06-09.json`: first-task Qwen Code SWE-bench Lite diagnostic. A/B/C are full, but the agent made 23 model calls and used about 0.90M tokens before being manually stopped after it tried to install missing test dependencies in the read-only container. The partial patch was unresolved; later runs use Qwen's native turn/tool/wall-time caps.
- `qwen-code-docker-openrouter-nvidia-swe-bench-lite-curated-10-bounded-2026-06-09.json`: Docker-isolated Qwen Code over the 10 curated SWE-bench Lite tasks with `QWEN_MAX_TOOL_CALLS=12`, `QWEN_MAX_SESSION_TURNS=12`, and `QWEN_MAX_WALL_TIME=8m`. A/B/C are full for all 10 runs. The strict benchmark solved count is 0/10 because cap exits are nonzero, while the SWE-bench oracle resolved 1/10 patches.

## Removed snapshots

Superseded snapshots (the three-task DeepSeek `initial-3` set, the four-task Nemotron `examples-full` set, the codex local/nvidia full runs, and the Aider architect smoke) were removed on 2026-06-10; they predate the metric fixes above and are recoverable from git history. Raw result and trace files remain under ignored `runs*/` directories when present locally.
