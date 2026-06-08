# Metric Coverage

The benchmark reports whether each RESEARCH.md metric is supported by the traces captured in a run set.

| Metric | Current support | What is required |
|---|---|---|
| Startup tax | Full for structured model-call traces. | First model-call `input_tokens` and task prompt token count. |
| Context growth rate | Full only when a run has at least two model calls. | Per-call `input_tokens` across turns. |
| Solve efficiency | Full when token usage and cost are present for every run. | Success labels plus model usage and pricing or native cost. |

Black-box CLIs can still produce full A/B/C coverage when they expose per-call usage natively or can be routed through the local usage-only proxy. The proxy writes model name, token counts, cache counts, status, and cost metadata into `.harness-usage-proxy.jsonl`; it does not store prompt or completion text by default.

Context growth needs at least two model calls in the run. Use `examples/tasks/metrics-calibration-multicall` when checking whether a harness can produce the B metric.

Known exceptions:

- Antigravity CLI Docker does not currently expose token usage or a documented routeable provider base URL. Use `antigravity-sdk` for usage metrics until the CLI or vendor support changes.
- Grok Build Docker is measurable only if the CLI exposes a routeable xAI/OpenAI-compatible base URL or native usage events. Otherwise it can be graded for success but not A/B/C.
