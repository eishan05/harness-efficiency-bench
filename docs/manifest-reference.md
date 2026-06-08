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

Docker-only agent CLI harnesses should use `adapter: docker_agent_cli` and include:

- `config.cli_version`: expected CLI/package version.
- `config.version_command`: command used to verify the installed CLI inside Docker.
- `config.required_env`: API-key env vars required before launch.
- `config.trace.parser`: native output parser name, usually `generic_json`, `goose_stream_json`, `kimi_stream_json`, or `opencode_json`.
- `config.trace.proxy`: optional usage-only OpenAI-compatible proxy config. Set `enabled: true`, `upstream_base_url`, `upstream_api_key_env`, `base_url_env`, `api_key_env`, and `trace_path`.
- `config.bench_ready: false`: use this when the image exists but the one-shot command path has not been smoke-verified.

OpenRouter variants should be separate manifests named `*-docker-openrouter.yaml`, require `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, and use `pricing: {}` unless native trace output includes cost or the manifest pins a single priced model. Prefer enabling `trace.proxy` for these variants so black-box CLIs can still emit per-call usage without storing request payloads.

Example proxy block:

```yaml
trace:
  parser: qwen_text_or_json
  proxy:
    enabled: true
    protocol: openai_compatible
    upstream_base_url: https://openrouter.ai/api/v1
    upstream_api_key_env: OPENROUTER_API_KEY
    base_url_env:
      - QWEN_BASE_URL
    api_key_env:
      - OPENROUTER_API_KEY
    trace_path: .harness-usage-proxy.jsonl
```

Claude Code can be configured as either a host debug harness or a Docker-isolated API-key harness. For serious runs, use `examples/harnesses/claude-code-docker-isolated.yaml`, build `docker/claude-code`, pass `ANTHROPIC_API_KEY`, and keep `pricing: {}` so native `total_cost_usd` from Claude Code is used.

## SWE-bench Prediction Export

Runs in Git-initialized workspaces capture `git diff --binary HEAD` as `artifacts.git_diff`.
Export prediction JSONL with:

```bash
harness-bench export-predictions --out predictions.jsonl
```

The exported records use `instance_id`, `model_name_or_path`, and `model_patch`, matching the shape expected by SWE-bench-style evaluation flows.
