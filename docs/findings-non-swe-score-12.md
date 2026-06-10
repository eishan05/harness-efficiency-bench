# What 12 coding agents cost to run the same job, and why

We took 12 coding-agent CLIs — Aider, Claude Code, Codex, Goose, Hermes, Kilo, Kimi Code, Nanobot, OpenClaw, Opencode, and Qwen Code (plus Aider's architect mode) — and gave every one of them the **same model** and the **same 12 small Python tasks** (fix a calculator, write a CSV reconciler, that kind of thing). A local proxy counted every token of every request. Then we ran the whole thing again on a second, completely different model to see which results were real and which were noise.

Nearly every agent solved nearly every task. That's the point: when the tasks are easy enough that everyone succeeds, the only thing left to measure is **what each agent charged you to get there**.

Here is what we saw, and the mechanics behind it.

---

## 1. Your agent choice can be a 40–70x difference in tokens — on the same model, same task

Tokens per solved task ranged from **~4,000 (Aider)** to **~190,000–290,000 (OpenClaw)**. Claude Code and Goose landed in the middle around 52–62k; Codex, Opencode and Nanobot around 72–90k; Kimi and Kilo around 105–120k; Qwen Code at 141–182k.

And this ordering barely changed when we swapped the model (rank correlation 0.993 between the two runs). The expensive agents were expensive on both models; the cheap ones were cheap on both.

**Why:** an agent's cost profile is a property of its *loop*, not of the model inside it. How big is its system prompt? How many tool calls does it make before it's satisfied? Does it re-read files it already saw? The model just fills in the blanks the harness hands it. People compare models obsessively and treat the harness as a neutral pipe. It is not a neutral pipe. It is most of the bill.

## 2. Every agent pays a "boot tax" before it reads your request — and it's wildly different

Before your prompt does anything, the agent ships its own baggage: system prompt, tool definitions, environment briefing, project conventions. We measured this directly — first request's input tokens minus your actual prompt:

| Agent | Boot tax (tokens) |
|---|---:|
| Aider (architect) | ~700 |
| Hermes | ~2,500 |
| Aider | ~3,000 |
| Goose | ~4,000–4,400 |
| Claude Code | ~4,500 |
| Codex / Opencode / Nanobot | ~8,000–10,000 |
| Kilo / Kimi | ~15,000–16,500 |
| Qwen Code | ~19,000–21,400 |
| OpenClaw | ~24,000–29,000 |

This was the most stable number in the whole benchmark: the ranking was **identical** on both models (rank correlation 1.000), and most values matched within ~5%. It's a constant of the software, like a binary's size.

**Why it matters more than it looks:** the boot tax isn't paid once. LLM APIs are stateless — the whole conversation, scaffolding included, is resent on *every* call. An agent with a 24k floor that makes 15 calls has spent 360k input tokens on scaffolding alone before you count any actual work. Total cost is roughly `calls × floor + history`, and the floor term dominates for heavy harnesses.

## 3. The expensive agents are NOT expensive because they "hoard context"

We expected the costly agents to be the ones whose conversations balloon fastest. Wrong. Once we measured growth properly, **every single agent grows its context at a few hundred tokens per turn** (roughly 160–560/turn), and the per-turn growth ranking didn't even replicate between the two models — it's noise.

**Why:** per-turn growth is just "tool output + model reply" appended to history, and on small tasks that's similar for everyone. What actually separated the agents was the *number of calls* they make and the *size of the floor* each call re-carries (finding #2). An agent that takes 20 turns with a 16k floor costs vastly more than one that takes 6 turns with a 4k floor, even at identical growth per turn. If you're optimizing an agent, attack the call count and the system-prompt size before you touch context management.

## 4. Raw token counts will lie to you about cost — caching is the reason

On the paid model, Codex consumed over 1M tokens for the suite — looks terrible. But ~70% of its input tokens were **cache reads**, which providers bill at roughly a tenth of the price. Weighted by what you'd actually pay, Codex drops to ~315k effective tokens — making it *cheaper per solved task than Claude Code*, despite "using" twice the tokens.

**Why:** resending the same conversation prefix every call (finding #2's stateless loop) is exactly the pattern prompt caching exists for. A harness that keeps its prefix byte-stable gets cheap cache hits on all that repetition; one that perturbs its prompt ordering breaks the cache and pays full price for the same tokens. Two consequences: (a) never compare agents on raw tokens without checking the cached share; (b) cache-friendliness is a real engineering property of a harness, worth as much as a smaller prompt. (Note: our free-tier model reported no caching at all — you only get this discount when the provider supports it.)

## 5. The cheapest "agent" wins by not being an agent

Aider solved 11/12 tasks at ~4–5k tokens each — roughly **10x cheaper than the mid-pack agentic CLIs** — because for tasks like these it makes *one* model call: here's the file, here's the request, give me the diff. No exploration loop, no tool calls, no re-reading.

**Why this is a general lesson and not an Aider ad:** the agentic loop (look around → act → check → repeat) is a *cost multiplier* you should pay only when the task actually needs iteration — unknown codebase, failing tests, multi-file changes. For a well-specified small edit, the loop mostly re-confirms things a single call could have assumed. Matching the harness to the task size is the single biggest cost lever in this data.

## 6. Your "single-model" agent might be quietly calling a second model

Two CLIs (Opencode and Kilo) send every task's title-generation request to **Claude Haiku**, regardless of what model you configured — we found this because the proxy logs the billed model per request, and it reproduced to the exact token across both batches. It's small (~1% of their usage) but it's a separate vendor, a separate bill, and a separate data-flow than the one you chose.

**Why it happens:** harnesses hardcode small helper calls (titles, summaries) to a cheap fast model. Reasonable engineering — but worth knowing if you have compliance constraints on where your code snippets go, or if you're benchmarking "one model" and assuming that's literally true.

## 7. If you measure agents yourself, the raw data will try to fool you

Three traps we fell into so you don't have to:

- **Summary events double-count.** One CLI ends its stream with a usage event equal to the *sum of the entire session*. Naively adding usage events doubled its measured cost and made its context growth look 25x worse than reality. Check whether the last event equals the sum of the others.
- **Exit codes lie about success.** One agent solved all 12 tasks but exited nonzero on 5 of them (it hit a wall-clock cap *after* finishing the work). Grading by exit code alone would have nearly doubled its cost-per-solved-task. Grade the artifact, not the process.
- **One run can't rank close competitors.** Our adjacent mid-table pairs swapped places between the two models. The big gaps (10x, 40x) are real; the 10% gaps are noise at n=1. We added a `--repeats` flag for exactly this.

---

## The short version

1. The harness is most of your bill. Same model, same tasks: 40–70x spread.
2. Every call resends the agent's whole scaffolding. Boot tax × call count is the dominant cost term, and boot tax ranges from ~700 to ~29,000 tokens.
3. Nobody's context grows meaningfully faster than anyone else's per turn. Call count and prompt floor are what differ.
4. Check cached-token share before trusting any token number. It flips rankings.
5. Use a one-shot tool for one-shot tasks; pay for the agentic loop only when iteration earns its keep.
6. Verify which models your agent actually calls.
7. If you benchmark: dedupe summary usage events, grade outcomes instead of exit codes, and repeat runs before ranking close pairs.

## Honest limits

Twelve small, well-specified Python tasks; two mid-size models served via one router; one run per cell (two counting the second model). This data says a lot about *cost structure* and nothing about *capability* — every agent here could do these tasks. Heavy scaffolding may well earn its cost back on hard, long-horizon work in big repositories; that's a different benchmark (our SWE-bench runs are telemetry-only so far). Snapshots, raw protocol, and metric definitions: `examples/results/`, `RESEARCH.md`, `docs/metric-coverage.md`.
