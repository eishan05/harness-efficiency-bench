# Same model, same tasks — one coding agent cost 70x more than another

I gave 12 coding-agent CLIs — Aider, Claude Code, Codex, Goose, Hermes, Kilo, Kimi Code, Nanobot, OpenClaw, Opencode, and Qwen Code — the exact same model and the exact same 12 small Python tasks, and counted every token each one spent. Then I ran the whole thing again on a second, completely different model to check which results were real and which were noise.

Almost every agent solved almost every task. That's what makes the comparison interesting: when everyone succeeds, the only question left is what each agent charged you to get there. The answers were not close.

## Results at a glance

| Agent | Tokens per solved task | Startup overhead (tokens) |
|---|---:|---:|
| Aider (architect mode) | ~3,500–4,100 | ~700 |
| Aider | ~4,100–5,000 | ~3,000 |
| Hermes | ~30,000–34,000 | ~2,500 |
| Claude Code | ~52,000–55,000 | ~4,500 |
| Goose | ~56,000–62,000 | ~4,000–4,400 |
| Opencode | ~72,000–80,000 | ~8,400–8,700 |
| Nanobot | ~74,000–84,000 | ~8,500–9,700 |
| Codex | ~85,000–90,000 | ~8,000–8,400 |
| Kimi Code | ~105,000–116,000 | ~16,000–16,500 |
| Kilo | ~119,000–120,000 | ~14,500–14,900 |
| Qwen Code | ~141,000–182,000 | ~19,000–21,400 |
| OpenClaw | ~191,000–292,000 | ~24,000–29,000 |

Each row shows the range across the two models. The ordering barely moved between them — the startup-overhead ranking didn't change at all, and the cost-per-task ranking changed by one adjacent swap.

## The agent is most of your bill

The same model, doing the same work, cost 40–70x more tokens depending on which CLI was driving it. That gap is bigger than any model-vs-model price difference you're likely to be weighing.

We argue endlessly about which model to use and treat the agent wrapped around it as a neutral pipe. It isn't a neutral pipe. How much scaffolding it ships, how many round-trips it takes before it's satisfied, whether it re-reads things it already saw — that loop, not the model, decided almost all of the cost in this data.

## Every agent pays a boot tax before it reads your prompt

Before your request does anything, the agent sends its own baggage: system prompt, tool descriptions, environment briefing. I measured that overhead directly, and it ranges from ~700 tokens (Aider in architect mode) to ~29,000 (OpenClaw) — a 40x spread.

This was the most stable number in the entire benchmark. The ranking was identical on both models, and most values matched within about 5%. It behaves like a constant of the software, the way a binary has a size.

Here's why it matters more than it looks: that overhead isn't paid once. Models don't remember anything between calls, so the whole conversation — scaffolding included — gets resent on every single round-trip. An agent with a 24k floor that takes 15 turns has spent 360k input tokens on scaffolding alone, before you count any actual work. Roughly: cost = turns × floor + the work itself. For the heavy agents, the floor term is most of the bill.

## The expensive agents are not "hoarding context" — they're just taking more turns

I expected the costly agents to be the ones whose conversations balloon fastest. Wrong. Every single agent grew its context at a few hundred tokens per turn — and the per-turn growth ranking didn't even replicate between the two models, which is a polite way of saying it's noise.

What actually separated the agents was how many turns they took and how big a floor each turn re-carried. Twenty turns with a 16k floor costs vastly more than six turns with a 4k floor, even if both conversations grow at the identical rate. If you're building or tuning an agent, attack the turn count and the prompt size before you touch anything fancier.

## Raw token counts will lie to you about cost

On the paid model, Codex burned over a million tokens for the suite — on paper, one of the worst. But about 70% of its input tokens were cache reads, which providers bill at roughly a tenth of the price. Priced the way you'd actually pay, Codex drops to ~315k effective tokens, which makes it cheaper per solved task than Claude Code — an agent that "used" half as many tokens.

The mechanism is the boot tax again, viewed from the other side: resending the same prefix every turn is exactly the pattern prompt caching exists for, and an agent that keeps its prefix stable gets all that repetition nearly free. Two implications. Never compare agents on raw tokens without checking the cached share — it flips rankings. And cache-friendliness is a real engineering virtue in an agent, worth as much as a smaller prompt. (One caveat: the free-tier model reported no caching at all. The discount only exists where the provider supports it.)

## The cheapest "agent" won by not being an agent

Aider solved 11 of 12 tasks at ~4–5k tokens each — roughly 10x cheaper than the mid-pack — because for tasks like these it doesn't run a loop at all. One call: here's the file, here's the request, give me the diff.

This isn't an Aider ad; it's a sizing lesson. The agentic loop — look around, act, check, repeat — is a cost multiplier that earns its keep on hard problems: unfamiliar code, failing tests, multi-file changes. On a well-specified small edit, the loop mostly re-confirms things a single call could have assumed. Matching the tool to the task size is the single biggest cost lever I found.

## Your "single-model" agent might not be

Two of the CLIs quietly sent a small request per task to a completely different model (Claude Haiku) — for generating conversation titles — regardless of what model I had configured. It's about 1% of their usage, so the cost is trivia. But it's a second vendor and a second place your code snippets travel, and I only knew because I was counting at the network level. If you have rules about where your code goes, "I configured model X" is not quite the same statement as "my agent only talks to model X."

## What I'd do with this

1. Pick the agent with at least as much care as the model. Same model, same tasks: 40–70x.
2. For small, well-specified edits, use a one-shot tool. Pay for the agentic loop only when iteration earns its keep.
3. Judge cost by what you're billed, not by raw token counts — check the cached share first.
4. If you're building an agent: cut turns and cut the prompt floor. Context growth per turn is not where the money is.
5. Know which models your agent actually calls.

## Honest limits

Twelve small Python tasks, two mid-size models, one run per pairing. This says a lot about cost structure and nothing about capability — every agent here could do these tasks. The heavy scaffolding that looks wasteful on a ten-minute fix may earn its cost back on hard, long-horizon work in a big repository; that's a different experiment. And the mid-table gaps (10–20%) are within noise — only the big gaps are worth repeating out loud.

I started by asking what a coding agent costs beyond the model it runs. The answer is: usually more than the model, paid mostly in scaffolding resent on every turn — and you can change it by changing the agent, without touching the model at all.
