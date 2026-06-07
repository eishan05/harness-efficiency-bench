# Manifest Reference

## Task Manifest

```yaml
id: toy-write-file
source: local
prompt: |
  Create answer.txt.
fixtures: fixtures
workspace_setup:
  git_init: true
  commands:
    - "python3 -m pip install -e ."
oracle:
  type: file_equals
  path: answer.txt
  text: |
    hello benchmark
budgets:
  timeout_sec: 120
perturbations:
  - id: 20k
    tokens: 20000
    seed: "irrelevant stale build log"
    placement: prompt_prefix
tags:
  - smoke
```

Supported oracle types:

- `none`
- `file_equals`
- `file_contains`
- `command`

Supported perturbation placements:

- `prompt_prefix`
- `prompt_suffix`

## Harness Manifest

```yaml
id: codex
adapter: codex
model: gpt-5.4
timeout_sec: 900
trace_mode: structured
pricing:
  input_per_million: 2.50
  cached_input_per_million: 0.25
  output_per_million: 15.00
permissions:
  sandbox: workspace-write
```

`pricing` is optional. If a structured trace already reports `cost_usd`, the benchmark preserves that native value.

## SWE-bench Prediction Export

Runs in Git-initialized workspaces capture `git diff --binary HEAD` as `artifacts.git_diff`.
Export prediction JSONL with:

```bash
harness-bench export-predictions --out predictions.jsonl
```

The exported records use `instance_id`, `model_name_or_path`, and `model_patch`, matching the shape expected by SWE-bench-style evaluation flows.
