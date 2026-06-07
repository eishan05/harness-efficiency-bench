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
model: gpt-5.5
timeout_sec: 900
trace_mode: structured
command:
  - codex
  - exec
  - --json
  - -c
  - model_provider="openai_api"
  - -c
  - model_providers.openai_api.env_key="OPENAI_API_KEY"
  - -c
  - model_providers.openai_api.supports_websockets=false
  - --sandbox
  - danger-full-access
  - --skip-git-repo-check
  - --model
  - "{model}"
  - "-"
pricing:
  input_per_million: 5.00
  cached_input_per_million: 0.50
  output_per_million: 30.00
  long_context_threshold_tokens: 272000
  long_context_input_per_million: 10.00
  long_context_cached_input_per_million: 1.00
  long_context_output_per_million: 45.00
permissions:
  sandbox: docker-container
config:
  backend: docker
  docker_image: harness-bench/codex-cli:0.137.0
  docker_network: bridge
  docker_memory: 4g
  docker_cpus: "2"
  docker_read_only: true
  docker_home: /codex-home
  docker_tmpfs:
    - /tmp:exec,size=2g
    - /codex-home:exec,size=512m
  docker_env_passthrough:
    - OPENAI_API_KEY
```

`pricing` is optional. If a structured trace already reports `cost_usd`, the benchmark preserves that native value.

Set `config.backend: docker` for Docker isolation. Docker harnesses run with `docker run --rm`, mount only the run workspace at `/workspace` by default, and can opt into `docker_network`, `docker_mounts`, `docker_env_passthrough`, `docker_memory`, `docker_cpus`, `docker_read_only`, and `docker_tmpfs`.

Claude Code can be configured as either a host debug harness or a Docker-isolated API-key harness. For serious runs, use `examples/harnesses/claude-code-docker-isolated.yaml`, build `docker/claude-code`, pass `ANTHROPIC_API_KEY`, and keep `pricing: {}` so native `total_cost_usd` from Claude Code is used.

## SWE-bench Prediction Export

Runs in Git-initialized workspaces capture `git diff --binary HEAD` as `artifacts.git_diff`.
Export prediction JSONL with:

```bash
harness-bench export-predictions --out predictions.jsonl
```

The exported records use `instance_id`, `model_name_or_path`, and `model_patch`, matching the shape expected by SWE-bench-style evaluation flows.
