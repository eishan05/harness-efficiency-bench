# Adding Harnesses

Harnesses are configured with a YAML manifest and, when needed, a Python adapter.

## Fast Path: Generic CLI

Use `generic_cli` when a harness can run a single command in a prepared workspace:

```yaml
id: my-agent
adapter: generic_cli
command: "my-agent --prompt-file {prompt_file} --workspace {workspace}"
timeout_sec: 900
trace_mode: partial
```

Available placeholders:

- `{prompt}`: shell-quoted prompt for string commands.
- `{prompt_file}`: path to the rendered prompt file.
- `{workspace}`: prepared task workspace.
- `{run_id}`, `{task_id}`, `{harness_id}`.
- `{model}`, `{model_endpoint}`.

Generic CLI runs can score oracle success and capture stdout/stderr. They only get full token metrics if the command also emits parseable traces or routes model calls through a proxy.

## Docker Execution

Command-based adapters can run inside Docker by setting `config.backend`. Use this mode for serious benchmark runs and combine it with `--require-docker-isolation`:

```yaml
id: my-agent-docker
adapter: generic_cli
command: "my-agent --prompt-file {prompt_file}"
config:
  backend: docker
  docker_image: ghcr.io/my-org/my-agent:latest
  docker_network: bridge
  docker_memory: 4g
  docker_cpus: "2"
  docker_tmpfs:
    - /tmp:exec,size=512m
  docker_env_passthrough:
    - OPENAI_API_KEY
```

The task workspace is mounted at `/workspace`, and `{prompt_file}` resolves to `/workspace/.benchmark_prompt.txt` inside the container. Containers are started with `docker run --rm`; the container is removed after execution, while benchmark results and traces are retained.

## Docker-Only Agent CLIs

Use `docker_agent_cli` for third-party agent CLIs that must never run on the host:

```yaml
id: my-agent-docker-isolated
adapter: docker_agent_cli
command: ["/opt/harness/run-agent", "{prompt_file}"]
trace_mode: structured
capabilities:
  - docker_isolation
config:
  backend: docker
  docker_image: harness-bench/my-agent:1.2.3
  cli_version: "1.2.3"
  version_command: ["my-agent", "--version"]
  required_env:
    - OPENAI_API_KEY
  docker_env_passthrough:
    - OPENAI_API_KEY
  trace:
    parser: generic_json
```

The adapter fails fast unless `config.backend: docker` is set. It also checks `required_env`, runs `version_command` when configured, and records version-check metadata in the result. Use `bench_ready: false` for images or wrappers that build but do not yet have a smoke-verified one-shot task path.

When adding an OpenRouter route, prefer a separate `*-docker-openrouter.yaml` manifest over changing the direct-provider manifest. Require both `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, and pass only those plus harness-specific model override env vars into Docker.

When the CLI can accept an OpenAI-compatible base URL, add a usage-only proxy block:

```yaml
trace:
  parser: generic_json
  proxy:
    enabled: true
    protocol: openai_compatible
    upstream_base_url: https://openrouter.ai/api/v1
    upstream_api_key_env: OPENROUTER_API_KEY
    base_url_env:
      - OPENROUTER_BASE_URL
    api_key_env:
      - OPENROUTER_API_KEY
    trace_path: .harness-usage-proxy.jsonl
```

The adapter starts the proxy for the run, injects the configured base URL env vars, and records usage-only JSONL. Do not enable proxy mode for CLIs without a verified base URL path; mark those harnesses unsupported for A/B/C until native usage, a routeable endpoint, or an upstream patch exists.

## First-Class Adapter

Add a Python adapter when the harness has structured JSON, JSONL, SDK events, or usage metadata.

1. Create `src/harness_efficiency_bench/adapters/<name>.py`.
2. Subclass `BaseAdapter`.
3. Return `AdapterResult` with normalized `TraceEvent` records.
4. Register the adapter in `adapters/registry.py`.
5. Add an example manifest under `examples/harnesses/`.

The important event for token metrics is:

```python
model_call_event(
    call_index=0,
    input_tokens=...,
    cached_input_tokens=...,
    output_tokens=...,
    reasoning_output_tokens=...,
)
```

## Current Adapter Intent

- `codex`: parses `codex exec --json`.
- `claude_code`: parses `claude -p --output-format stream-json`, including per-turn usage, native final cost, and tool result output.
- `docker_agent_cli`: Docker-only command wrapper for agent CLIs, with required env checks, CLI version preflight, and generic JSON/JSONL/proxy usage parsing.
- `antigravity`: prefers `google-antigravity` SDK; supports `agy -p` fallback.
- `qwen_code`: runs `qwen -p`; richer parsing can be added once local JSON output is available.
- `nanobot`: Docker wrapper can generate a minimal OpenRouter config; custom deployments can still use `NANOBOT_RUN_COMMAND`.
- `mini_swe_agent`: requires a local command/wrapper because versions differ.
