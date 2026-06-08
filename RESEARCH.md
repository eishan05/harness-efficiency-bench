# Harness Efficiency Research

For different harnesses, across different models, measure the following metrics.

## A. Startup Tax

```text
startup_tax = first_model_call_input_tokens - user_prompt_tokens
```

This captures how much the harness injects before the agent does real work.

## B. Context Growth Rate

```text
growth_rate = Δ input_tokens_per_call / Δ turn
```

This tells you how quickly the harness accumulates baggage.

## C. Solve Efficiency

```text
token_cost_per_solved_task =
  (total_input_tokens + output_tokens + reasoning_output_tokens)
  / number_of_successful_tasks
```

This matters more than raw bloat: a harness that spends more tokens but solves more tasks may still be better. If cached input is reported separately, it is included once through total input tokens.

## D. Context-Bloat Harm Curve

Run the same task with controlled irrelevant or stale context added:

```text
success_rate(context = 20k, 50k, 100k, 200k, ...)
```

The slope of degradation is the "context rot" signal. LOCA-bench is aligned with this idea.
