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
    input_text="optional raw model-call input for retention",
)
```

If `input_text` is omitted, exact tool-output retention is marked unsupported.

## Current Adapter Intent

- `codex`: parses `codex exec --json`.
- `claude_code`: parses `claude -p --output-format stream-json`.
- `antigravity`: prefers `google-antigravity` SDK; supports `agy -p` fallback.
- `qwen_code`: runs `qwen -p`; richer parsing can be added once local JSON output is available.
- `nanobot`: requires a local command/wrapper because deployments differ.
- `mini_swe_agent`: requires a local command/wrapper because versions differ.
