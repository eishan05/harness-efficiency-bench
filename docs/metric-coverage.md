# Metric Coverage

The benchmark reports whether each RESEARCH.md metric is supported by the traces captured in a run set.

| Metric | Current support | What is required |
|---|---|---|
| Startup tax | Full for structured per-call traces; partial for aggregate-only token usage. | Provider-first startup tax plus task-first startup tax when those are distinct calls. |
| Context growth rate | Full only when a run has at least two non-aggregate, non-preflight model calls. | Per-call `input_tokens` across turns. |
| Solve efficiency | Full when token usage is present for every run. | Success labels plus total input, output, and reasoning tokens. |

Black-box CLIs can still produce full A/B/C coverage when they expose per-call usage natively or can be routed through the local usage-only proxy. The proxy writes model name, request id, token counts, cache counts, status, and cost metadata into `.harness-usage-proxy.jsonl`; it does not store prompt or completion text by default.

Startup tax has two components when a harness emits billable provider requests that are not visible task/model turns: `provider_first_startup_tax` is the literal first billable provider request minus task prompt tokens, and `task_first_startup_tax` is the first non-preflight task/model request minus task prompt tokens. If both components refer to the same call, the call is counted once. If they refer to distinct calls, the reported startup tax is their sum.

Startup tax is unsupported for a run when the reported first-call `input_tokens` is smaller than the benchmark's rendered prompt token estimate. That usually means the harness/provider trace did not account for the full injected prompt in that request, so subtracting the prompt estimate would produce a misleading negative overhead.

Context growth needs at least two non-aggregate, non-preflight model calls in the run. Claude Code Docker OpenRouter routes Anthropic-compatible OpenRouter traffic through the usage proxy; when OpenRouter returns per-request usage, that trace is sufficient for full A/B/C. Proxy requests that do not correspond to visible Claude assistant messages are retained for solve-efficiency token totals and provider-first startup tax, but ignored for context-growth calculations. Aggregate run-level usage, such as Claude Code OpenRouter `modelUsage`, is enough for solve efficiency but not enough for full startup-tax or context-growth measurement. Use `examples/tasks/metrics-calibration-multicall` when checking whether a harness can produce the B metric.

Excluded from the A/B/C comparison set:

- Antigravity CLI Docker does not currently expose token usage or a documented routeable provider base URL. It can be graded for task success, but it is not an A/B/C candidate.
- Grok Build Docker does not currently expose enough routeable or native usage telemetry for correct A/B/C measurement. It can be graded for task success, but it is not an A/B/C candidate.

The Docker OpenRouter calibration snapshot in `examples/results/openrouter-docker-smoke-calibration-2026-06-08.json` shows full startup-tax and solve-efficiency token coverage for the measurable OpenRouter harnesses. Context growth is full whenever the task produces at least two model calls; a one-call task can still report context growth as unsupported because there is no growth slope to fit.
