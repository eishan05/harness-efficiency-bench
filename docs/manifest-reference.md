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
- `swe_bench`

Supported perturbation placements:

- `prompt_prefix`
- `prompt_suffix`

SWE-bench tasks use a Git checkout instead of local fixtures and grade with the official Docker evaluator:

```yaml
workspace_setup:
  git_clone:
    repo: django/django
    base_commit: 2f72480fbd27896c986c45193e1603e35c0b19a7
oracle:
  type: swe_bench
  dataset_name: SWE-bench/SWE-bench_Lite
  split: test
  instance_id: django__django-11905
  arch: auto
  namespace: auto
  max_workers: 1
  cache_level: env
```

`arch: auto` resolves to the Docker host architecture (`x86_64` or `arm64`). `namespace: auto` uses official `swebench/*` remote images on `x86_64` and local `sweb.*` image builds on `arm64`, because the official remote eval images are amd64-only. Set `namespace: none` to force local image builds.

The runner uses `.cache/harness-bench/repos` as a Git mirror cache by default. Pass `--repo-cache <path>` or `--no-repo-cache` on `run-task`/`run-suite` to change that behavior.

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
- `config.trace.proxy`: optional usage-only provider proxy config for OpenAI-compatible or Anthropic-compatible traffic. Set `enabled: true`, `upstream_base_url`, `upstream_api_key_env`, `base_url_env`, `api_key_env`, and `trace_path`.
- `config.bench_ready: false`: use this when the image exists but the one-shot command path has not been smoke-verified.

OpenRouter variants should be separate manifests named `*-docker-openrouter.yaml`, require `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, and use `pricing: {}` unless native trace output includes cost or the manifest pins a single priced model. Prefer enabling `trace.proxy` for OpenAI-compatible variants so black-box CLIs can still emit per-call usage without storing request payloads. Docker-backed proxy runs bind the local proxy to `0.0.0.0` during the run so the container can reach it through `host.docker.internal`; host runs stay loopback-only by default. For Git-based tasks, prefer a proxy `trace_path` outside the mounted workspace, such as `../.harness-usage-proxy.jsonl`, so the agent cannot read trace metadata and the file does not enter task diffs.

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

Claude Code can be configured as a host subscription harness, host API-key harness, Docker-isolated API-key harness, or OpenRouter harness. For direct Anthropic serious runs, use `examples/harnesses/claude-code-docker-isolated.yaml`, build `docker/claude-code`, pass `ANTHROPIC_API_KEY`, and keep `pricing: {}` so native `total_cost_usd` from Claude Code is used. For benchmark-ready OpenRouter runs, use `claude-code-docker-openrouter.yaml`; the adapter maps `OPENROUTER_API_KEY` to `ANTHROPIC_AUTH_TOKEN`, routes `ANTHROPIC_BASE_URL` through the usage proxy, and keeps Claude Code `modelUsage` as an aggregate fallback for C when per-request usage is unavailable. Set `CLAUDE_MAX_BUDGET_USD` to override Claude Code's Docker CLI budget guard for long tasks. The host `claude-code-openrouter.yaml` remains a debug harness unless its run metadata shows `selected_trace_source: proxy`.

Codex OpenRouter runs use `examples/harnesses/codex-docker-openrouter.yaml`. The manifest configures a custom Codex `model_provider` named `openrouter`, uses `wire_api="responses"` for OpenRouter's OpenAI-compatible `/api/v1/responses` route, resolves `model: ${OPENROUTER_MODEL}` before command rendering, and keeps `codex_rollout_trace: true` for token metrics when Codex emits rollout traces.

## SWE-bench Prediction Export

Runs in Git-initialized workspaces capture `git diff --binary HEAD` as `artifacts.git_diff`.
Export prediction JSONL with:

```bash
harness-bench export-predictions --out predictions.jsonl
```

The exported records use `instance_id`, `model_name_or_path`, and `model_patch`, matching the shape expected by SWE-bench-style evaluation flows.
