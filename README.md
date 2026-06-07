# Harness Efficiency Bench

Benchmark coding-agent harnesses on token efficiency, context growth, tool-output retention, cost, and solve rate.

The v1 scaffold is designed around small task manifests and pluggable harness adapters. It can run a toy benchmark immediately, and it includes adapter entry points for Codex, Claude Code, Antigravity, Qwen Code, mini-swe-agent, nanobot, generic command-line harnesses, and Docker-only agent CLIs.

## Quick Start

Run the deterministic demo harness:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/demo.yaml
```

Run only Docker-isolated harnesses:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/generic-cli-docker.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Build the example Codex Docker image:

```bash
docker build -t harness-bench/codex-cli:0.137.0 docker/codex-cli
```

Run a low-cost Codex Docker smoke task:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/codex-docker-cheap.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Build the Claude Code Docker image and run the Docker-isolated API-key harness:

```bash
docker build -t harness-bench/claude-code:2.1.114 docker/claude-code
ANTHROPIC_API_KEY=... PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/claude-code-docker-isolated.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Build and run a Docker-only agent CLI harness:

```bash
docker build -t harness-bench/goose:1.37.0 docker/goose
OPENAI_API_KEY=... PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/goose-docker-isolated.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Preview Docker cleanup:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker
```

Remove benchmark-owned Docker images and optional build cache:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker --force --include-build-cache
```

Run the same task across all configured context-bloat perturbations:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/demo.yaml \
  --all-perturbations
```

Aggregate results:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli report
```

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Design

- **Tasks** define prompts, fixtures, oracle grading, budgets, and optional context perturbations.
- **Harnesses** define an adapter and execution settings.
- **Adapters** normalize each agent into a common run interface.
- **Traces** use JSONL events so metrics can be recomputed from raw data.
- **Metrics** are marked as full, partial, or unsupported based on trace visibility.
- **Isolation** is explicit in each result. Host runs are for debugging; serious runs should use Docker-backed harnesses with `--require-docker-isolation`.

Full observability requires either structured SDK/CLI events or visibility into model-call payloads through a proxy such as LiteLLM/OpenTelemetry. Black-box CLI runs can still be scored for success and runtime, but startup tax, context growth, and retention may be partial.

The starter task set includes:

- `toy-write-file`: deterministic smoke/context-rot task.
- `python-fix-calculator`: small Python bug-fix task.
- `harness-stress-log-triage`: log-heavy bug-fix task intended to stress tool-output retention.

Claude Code harnesses are split by auth and isolation:

- `claude-code`: host/local subscription debug harness. Requires `claude auth status` to show working account access.
- `claude-code-api`: host/API-key debug harness. Requires `ANTHROPIC_API_KEY`.
- `claude-code-docker-isolated`: Docker-isolated API-key harness for serious runs. Requires `ANTHROPIC_API_KEY` and the image build above.

Antigravity CLI is split into host debug and Docker-isolated OAuth modes:

- `antigravity-cli`: host/local CLI debug harness.
- `antigravity-sdk`: host/local SDK debug harness.
- `antigravity-cli-docker-isolated`: Docker-isolated CLI harness. Requires the `docker/antigravity` image and a dedicated `ANTIGRAVITY_AUTH_DIR` mounted into the container's Antigravity config directory.

Use a persistent `ANTIGRAVITY_AUTH_DIR`, such as `~/.harness-bench/antigravity-auth`, to avoid repeating Google OAuth between runs. OAuth is needed again only if that directory is deleted, the token is revoked/expired, or you switch to a different auth directory.

Docker-only agent CLI harnesses are API-key only and do not mount host OAuth or subscription state. Direct-provider examples are available for `goose`, `qwen-code`, `kimi-code`, `aider`, `opencode`, `kilo`, `nanobot`, `openclaw`, `hermes-agent`, and `grok-build`. Manifests marked `bench_ready: false` are scaffolds that still need live provider-key smoke verification before serious comparisons.

OpenRouter variants are available as `*-docker-openrouter.yaml` manifests for Docker CLIs except Grok Build, which uses xAI directly. Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, for example:

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/aider-docker-openrouter.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Grok Build uses xAI directly. Set `XAI_API_KEY` for `examples/harnesses/grok-build-docker-isolated.yaml`; the wrapper also accepts `GROK_CODE_XAI_API_KEY` for compatibility.

## Adding Harnesses

Start with `examples/harnesses/generic-cli.yaml` if the harness can run one command and exit. Use a first-class adapter when the harness emits structured events or has an SDK. See `docs/adding-harnesses.md`.
