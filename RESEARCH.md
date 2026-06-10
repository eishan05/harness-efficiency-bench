# Harness Efficiency Research

For different harnesses, across different models, measure the following metrics.

## A. Startup Tax

```text
startup_tax = first_model_call_input_tokens - user_prompt_tokens
```

This captures how much the harness injects before the agent does real work. When a harness emits a billable auxiliary request before the first task call (for example title generation), the reported startup tax is the sum of the auxiliary overhead and the task-first overhead, since both are injected before real work; the two components are reported separately in the metric details.

Auxiliary helper calls are identified two ways: by size (a tiny leading call far below the first real task call) and by model (a call billed to a different model than the one carrying the task conversation, which some CLIs use for title generation). Model-mismatch detection also catches helper calls that appear mid-run, where the size heuristic never looks.

## B. Context Growth Rate

```text
growth_rate = Δ input_tokens_per_call / Δ turn
```

This tells you how quickly the harness accumulates baggage.

The slope is fit over the dominant conversation thread. Some harnesses interleave a separate smaller sub-conversation mid-run; calls are segmented into monotone threads and the growth rate is measured per turn of the largest thread, with excluded calls listed in the metric details.

As a sanity diagnostic, each fit also reports the median adjacent per-call delta. When the fitted slope and the median delta diverge by more than 2x, the run is flagged (`slope_median_divergence`) and the ratio recorded: mild ratios (~2-3) mean front-loaded growth within a real conversation, while an order-of-magnitude ratio is the signature of an aggregate summary event or interleaved thread that slipped past structural detection.

## C. Solve Efficiency

```text
token_cost_per_solved_task =
  (total_input_tokens + output_tokens + separately_billed_reasoning_tokens)
  / number_of_successful_tasks
```

This matters more than raw bloat: a harness that spends more tokens but solves more tasks may still be better. If cached input is reported separately, it is included once through total input tokens. Reasoning tokens reported as a breakdown of completion/output tokens (OpenAI-compatible `completion_tokens_details`) are already inside output tokens and are not added again.

Solve efficiency is reported with two denominators:

- **strict**: the run passed the oracle and the harness exited zero. This is the operational metric, but it penalizes runs that pass the oracle and then exit through a wall-time or budget cap.
- **oracle**: the run passed the oracle, regardless of exit code. This is the task-outcome metric and the right denominator when runs are bounded by external caps.

A cache-discounted variant weights cached input tokens at 0.1 instead of full price (most providers bill cache reads at roughly a tenth of the uncached input rate), approximating dollar cost in token units. Harnesses differ enormously in how much provider-side caching they trigger, so the raw-token and cache-discounted rankings can disagree; both are reported.

Because some CLIs route helper requests to a different model than the configured one, batch summaries also report tokens per billed model (`model_usage`), which discloses any cross-model leakage inside a nominally single-model comparison.

## D. Context-Bloat Harm Curve

Run the same task with controlled irrelevant or stale context added:

```text
success_rate(context = 20k, 50k, 100k)
```

The slope of degradation is the "context rot" signal. LOCA-bench is aligned with this idea.
