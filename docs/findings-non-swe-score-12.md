# I ran 12 coding harnesses on the same model. The worst cost 70x more.

Everyone compares models. Almost nobody compares the harness, the CLI tool that wraps the model and drives it. I wanted to know how much that wrapper actually costs.

So I took 12 coding harnesses (Aider, Claude Code, Codex, Goose, Hermes, Kilo, Kimi Code, Nanobot, OpenClaw, Opencode, and Qwen Code) and gave all of them the same model and the same 12 small Python tasks. Fix a calculator, write a CSV reconciler, that kind of thing. Everything ran through OpenRouter so every harness was hitting the same API with the same model behind it. I counted every token. Then I ran the entire thing a second time on a completely different model to see which results were real and which were luck.

The first run used DeepSeek V4 Flash. The second used Nvidia's Nemotron 3 Ultra, which has a free tier on OpenRouter, so if you want to reproduce any of this, the second run costs you nothing.

Almost every harness solved almost every task. That's actually what makes the comparison work. When everyone succeeds, the only question left is what each one charged you to get there.

After both runs, the answer was blunter than I expected:

**The harness decides most of your bill. The same model, doing the same work, cost anywhere from 4,000 to 290,000 tokens per task depending on which CLI was driving it.**

## Results at a glance

Tokens spent per solved task, with the range across the two models:

| Harness | Tokens per solved task | Startup overhead |
|---|---:|---:|
| Aider (architect mode) | ~3,500-4,100 | ~700 |
| Aider | ~4,100-5,000 | ~3,000 |
| Hermes | ~30,000-34,000 | ~2,500 |
| Claude Code | ~52,000-55,000 | ~4,500 |
| Goose | ~56,000-62,000 | ~4,000 |
| Opencode | ~72,000-80,000 | ~8,500 |
| Nanobot | ~74,000-84,000 | ~9,000 |
| Codex | ~85,000-90,000 | ~8,200 |
| Kimi Code | ~105,000-116,000 | ~16,000 |
| Kilo | ~119,000-120,000 | ~14,700 |
| Qwen Code | ~141,000-182,000 | ~20,000 |
| OpenClaw | ~191,000-292,000 | ~26,000 |

The ordering barely moved between DeepSeek and Nemotron. The startup overhead ranking didn't change at all. The cost-per-task ranking changed by one adjacent swap. Whatever these numbers are measuring, it's baked into the harness software itself.

## The startup tax

Before your prompt does anything, the harness sends its own baggage: system prompt, tool descriptions, environment setup. Aider in architect mode ships about 700 tokens of overhead. OpenClaw ships about 26,000. That's a 40x difference before any work has started.

This was the most stable number in the whole benchmark. It came out nearly identical on both models, for every harness. It behaves like a constant of the software, the way a binary has a size.

And it matters way more than it looks, because it isn't paid once. Models don't remember anything between calls, so the whole conversation, baggage included, gets resent on every round-trip. A harness with a 26k floor that takes 15 turns has spent around 390k input tokens on its own scaffolding before you count any actual work. The startup tax times the number of turns is most of the bill for the heavy harnesses.

## The expensive harnesses aren't hoarding context

I expected the costly harnesses to be the ones whose conversations balloon the fastest. That's not what the data shows. Every harness grew its context at a few hundred tokens per turn, and the growth-rate ranking didn't even hold up between the two models. It's noise.

What actually separated them was how many turns they take and how big a floor each turn re-carries. Twenty turns with a 16k floor costs vastly more than six turns with a 4k floor, even when both conversations grow at the same rate. If you're building or tuning a harness, cut turns and cut the prompt floor before you touch anything fancier.

## Cached tokens flip the rankings

On the DeepSeek run, Codex burned over a million tokens for the suite. On paper, one of the worst. But about 70% of its input tokens were cache reads, which providers bill at roughly a tenth of the normal price. Priced the way you'd actually pay, Codex comes out cheaper per solved task than Claude Code, a harness that used half as many raw tokens.

This makes sense once you remember the startup tax. Resending the same prefix every turn is exactly the pattern prompt caching was built for, and a harness that keeps its prefix stable gets all that repetition nearly free. So two lessons. Never compare harnesses on raw token counts without checking the cached share, because it flips rankings. And being cache-friendly is a real engineering virtue in a harness, worth as much as a smaller prompt.

One catch: Nemotron's free tier reported no caching at all. The discount only exists where the provider supports it.

## The cheapest harness won by not being agentic

Aider solved 11 of the 12 tasks at around 4-5k tokens each. That's roughly 10x cheaper than the middle of the pack. It wins because for tasks like these it doesn't run a loop at all. One call: here's the file, here's the request, give me the diff.

The agentic loop (look around, act, check, repeat) is a cost multiplier. It earns its keep on hard problems: unfamiliar code, failing tests, changes that span files. On a small, well-described edit, the loop mostly re-confirms things a single call could have assumed. Matching the harness to the size of the task is the biggest cost lever I found in this entire dataset.

## So I ran the hard tasks too

The obvious objection to all of this: maybe the heavy scaffolding earns its cost back on hard problems. Fair. So I took four harnesses spanning the cost spectrum (Aider, Claude Code, Codex, and Kilo) and ran them on 10 real SWE-bench Lite tasks with generous limits. No tight budgets, no 90-second timeouts. Let them work.

All four resolved exactly one task out of ten. The same task.

Aider got there on 0.8M tokens. Claude Code spent 5.3M. Kilo spent 12.3M. Codex spent 15M. An 18x spread in spending, identical results. I even reran Claude Code with five times its earlier budget to make sure I wasn't strangling it. It produced real patches on nine of ten tasks instead of one, and not a single extra one resolved.

Harnesses still have a job on hard tasks. But when the model can't solve the problem, no amount of scaffolding rescues it. DeepSeek V4 Flash is a capable small model, but these tasks were past its ceiling, and the expensive loops just circled that ceiling at 15M tokens instead of finding a way over it. Capability comes from the model. The harness decides how expensive it is to find that out.

## Then I stuffed the context with garbage

The other thing I wanted to test was context rot directly. Same 12 small tasks, but with 20k, 50k, or 100k tokens of irrelevant log noise injected in front of the actual request. Same four harnesses.

The first surprise: the model doesn't rot. Aider passes the whole 100k mess to the model in one call, and it solved 12/12 anyway. Whatever folklore says about long context making models dumb, at 100k tokens on these tasks, it didn't.

The second surprise: Claude Code fell off a cliff. Perfect through 50k, then 2 out of 12 at 100k. It faithfully sends the full context, then after two or three calls it loses the plot. The runs end with no edits, as if the actual task drowned in the noise. Same model that Aider used to go 12/12. The failure sits in Claude Code's context pipeline.

The third surprise was Kilo's curve: perfectly flat, and suspiciously cheap. It solved everything at every level while its token count barely moved. The reason: it silently throws away most of the prompt. The 100k payload arrived at the model as 13k. It looks robust on a chart, but a harness that quietly drops your input when it gets large is not something I'd call robust. Next time, the thing it drops might be the part you needed.

Codex was the only looping harness that was both honest and sturdy: full payload, every call, 12/12 at every level. The price of that honesty is the boot-tax math again: it re-sends the garbage on every turn, so 100k of junk turned an 82k task into a 909k one. Eleven times the cost, paid entirely for noise it was too polite to drop.

After seeing Kilo's trick, I probed all twelve harnesses at the 100k level and checked, at the network layer, how much of the prompt each one actually transmitted. Seven of twelve passed it through faithfully. Two (Kilo and Opencode) silently dropped 85-90% of it and "solved" the tasks anyway. One (OpenClaw) checked the size up front, refused to run, and told me to use a larger-context model. Annoying, but honest. One (Kimi Code) just crashed with an unhandled exception. And Claude Code transmitted everything and lost the plot. Five different behaviors for the same oversized input, and not one of them is visible from the harness's output alone.

So: keep your prompts clean. The model can handle the junk; your harness's bill and your harness's attention often can't. And know which of these behaviors your harness has, because "it still worked" can mean it coped, or it can mean it never read what you sent.

## What I'd actually do with this

If you're working through small, well-specified tasks, use a one-shot harness like Aider and pocket the 10x. Bring in the heavy harnesses when the problem genuinely needs exploration and iteration.

If you're choosing between harnesses, weigh that choice at least as heavily as the model choice. The spread between harnesses was 40-70x. No model pricing difference comes close.

If you're looking at token dashboards, check the cached share before believing any number. And if you're picky about where your code goes, check which models your harness actually calls. The model you configured and the models on the wire can differ.

## The honest limits

The core numbers come from twelve small Python tasks, two models served through OpenRouter, one run per pairing. The SWE-bench and garbage-context follow-ups used four harnesses and one model, so those are strong results about one model and I hold them more loosely. A frontier model might give the heavy scaffolding more to work with on hard tasks; that experiment costs real money and I haven't run it.

But the original question has an answer. Most of what you pay for in an AI coding session goes to the harness re-sending its own packaging, turn after turn. The model supplies the capability. The harness sets the price. And you can change the harness without touching the model.
