# Metric Coverage

The benchmark reports whether each RESEARCH.md metric is supported by the traces captured in a run set.

| Metric | Current support | What is required |
|---|---|---|
| Startup tax | Full for structured model-call traces. | First model-call `input_tokens` and task prompt token count. |
| Context growth rate | Full only when a run has at least two model calls. | Per-call `input_tokens` across turns. |
| Tool-output retention ratio | Full only for traces with tool outputs and exact model input text. | `tool_result` outputs plus later `model_call.input_text`. |
| Solve efficiency | Full when token usage and cost are present for every run. | Success labels plus model usage and pricing or native cost. |
| Context-bloat harm curve | Full when base and perturbed runs are both present. | Run with `--all-perturbations` or explicit perturbation sweeps. |

Black-box CLIs can still produce useful solve-rate and cost data when they emit usage. For Docker-only agent CLIs, prefer native JSON/JSONL usage or a LiteLLM-style proxy trace written into the run workspace. Exact tool-output retention needs more observability than most CLIs expose by default; keep raw request payload retention opt-in because it can contain prompts, tool output, repo paths, and credentials.
