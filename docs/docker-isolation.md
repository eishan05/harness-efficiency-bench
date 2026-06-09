# Docker Isolation

Host execution is useful for debugging, but it is not safe for untrusted or large-scale benchmark runs. In host mode, the agent process runs on the host with its current directory set to the per-run workspace.

For serious runs, use Docker-backed harnesses and pass `--require-docker-isolation`:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/generic-cli-docker.yaml \
  --require-docker-isolation \
  --delete-workspace
```

Docker-backed harnesses use `docker run --rm`. The container is removed automatically. The benchmark workspace is kept unless `--delete-workspace` is passed; results and traces are always kept.

Docker images and build cache are not removed automatically. Preview cleanup with:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker
```

Remove benchmark-labeled containers, benchmark-owned images such as `harness-bench/*`, and optionally BuildKit cache:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker --force --include-build-cache
```

The cleanup command is dry-run by default. It removes images only by repository prefix, defaulting to `harness-bench/`; it does not remove arbitrary Docker images.

SWE-bench evaluation creates official `sweb.*` images. They are kept by default because rebuilding or pulling them is expensive. Remove them explicitly when you need the disk back:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker --force --include-swebench
```

The SWE-bench oracle itself runs inside `harness-bench/swebench-oracle:4.1.0` and mounts `/var/run/docker.sock` so the official evaluator can launch nested evaluation containers without installing `swebench` on the host. Build it with:

```bash
docker build -t harness-bench/swebench-oracle:4.1.0 docker/swebench-oracle
```

## Codex

Build the example Codex CLI image:

```bash
docker build -t harness-bench/codex-cli:0.137.0 docker/codex-cli
```

Then run:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/codex-docker-isolated.yaml \
  --require-docker-isolation
```

For low-cost smoke runs, use `examples/harnesses/codex-docker-cheap.yaml`, which uses `gpt-5.1-codex-mini` with low reasoning and verbosity:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/codex-docker-cheap.yaml \
  --require-docker-isolation \
  --delete-workspace
```

The example Codex Docker harnesses pass `OPENAI_API_KEY` from the host environment into the container and configure a Codex provider that reads that env var. They do not mount the host Codex home directory by default.

## Claude Code

Build the example Claude Code image:

```bash
docker build -t harness-bench/claude-code:2.1.114 docker/claude-code
```

Then run the Docker-isolated harness:

```bash
ANTHROPIC_API_KEY=... PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/claude-code-docker-isolated.yaml \
  --require-docker-isolation \
  --delete-workspace
```

The Docker harness passes only `ANTHROPIC_API_KEY` from the host. It does not mount the host Claude config or OAuth credentials.

## Antigravity CLI

Build the Antigravity CLI image:

```bash
docker build -t harness-bench/antigravity-cli:1.0.6 docker/antigravity
```

Antigravity CLI uses Google OAuth rather than an API key. For Docker-isolated runs, use a dedicated auth directory instead of mounting your host home:

```bash
mkdir -p /tmp/harness-antigravity-auth
export ANTIGRAVITY_AUTH_DIR=/tmp/harness-antigravity-auth
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/toy-write-file/task.yaml \
  --harness examples/harnesses/antigravity-cli-docker-isolated.yaml \
  --require-docker-isolation \
  --delete-workspace
```

The first run may print a Google OAuth URL and wait for an authorization code. Once authenticated, later runs reuse only the dedicated `ANTIGRAVITY_AUTH_DIR`; they do not mount the host Antigravity or Gemini home directory.

Use a persistent auth directory if you do not want to repeat OAuth after `/tmp` is cleaned:

```bash
mkdir -p ~/.harness-bench/antigravity-auth
export ANTIGRAVITY_AUTH_DIR=~/.harness-bench/antigravity-auth
```

If you initially authenticated with `/tmp/harness-antigravity-auth`, copy that state into the persistent directory:

```bash
mkdir -p ~/.harness-bench/antigravity-auth
cp -a /tmp/harness-antigravity-auth/. ~/.harness-bench/antigravity-auth/
export ANTIGRAVITY_AUTH_DIR=~/.harness-bench/antigravity-auth
```

OAuth must be repeated only if the auth directory is deleted, the refresh token is revoked or expires, Google invalidates the session, or a different `ANTIGRAVITY_AUTH_DIR` is used.

## Additional Docker-Only Agent CLIs

The repository includes Docker harness manifests and images for `goose`, `qwen-code`, `kimi-code`, `aider`, `opencode`, `kilo`, `nanobot`, `openclaw`, `hermes-agent`, and `grok-build`.

Build an image with:

```bash
docker build -t harness-bench/goose:1.37.0 docker/goose
```

Then run the matching `examples/harnesses/*-docker-isolated.yaml` manifest with `--require-docker-isolation`. These harnesses are API-key only: they pass selected environment variables into an isolated container home, and they do not mount host OAuth or subscription directories.

Tier 1 manifests are intended to be directly runnable after image build and API-key setup. Manifests marked `bench_ready: false` are registered with pinned image scaffolds, but their image builds and one-shot command paths still need live smoke verification before serious benchmark runs.

OpenRouter-specific variants use the same images and are named `*-docker-openrouter.yaml`. They are available for `codex`, `claude-code`, `goose`, `qwen-code`, `kimi-code`, `aider`, `opencode`, `kilo`, `nanobot`, `openclaw`, and `hermes-agent`. They require:

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"
```

These manifests keep provider-specific baselines unchanged while letting the same CLI run through OpenRouter. Claude Code uses OpenRouter's Anthropic-compatible `https://openrouter.ai/api` gateway; Codex and the other OpenRouter manifests use OpenAI-compatible routing when the CLI supports it. Trace quality depends on each CLI's output; many OpenRouter runs are black-box or partial even when the task oracle passes. Grok Build is not an OpenRouter variant; use `XAI_API_KEY` or `GROK_CODE_XAI_API_KEY` with `grok-build-docker-isolated.yaml`.

The OpenRouter smoke calibration in `examples/results/openrouter-docker-smoke-calibration-2026-06-08.json` confirms A/B/C token coverage for the measurable Docker harnesses when the task produces enough model calls. Antigravity CLI and Grok Build are intentionally excluded from the A/B/C comparison set because their CLIs do not currently expose correct token telemetry through routeable provider traffic or native usage events.

For Aider, use `AIDER_ARCHITECT=1` when measuring B context growth. Normal Aider mode is often a single model call, so B is unsupported even when A and C are available. The wrapper defaults to `AIDER_FILE_MODE=auto`: small repositories get tracked files added to the chat, while large repositories use repo-map mode instead of passing every tracked file. On the OpenRouter free `nvidia/nemotron-3-ultra-550b-a55b:free` model, SWE-scale Aider runs with repo-map context have stalled before usage is returned; `AIDER_MAP_TOKENS=0` is bounded and measurable but usually produces empty SWE patches.

For Qwen Code, use `QWEN_MAX_TOOL_CALLS`, `QWEN_MAX_SESSION_TURNS`, and `QWEN_MAX_WALL_TIME` to bound unattended SWE-scale runs. Qwen exits nonzero when a cap is exceeded, but the benchmark still grades any produced patch with the task oracle and preserves both strict benchmark success and `oracle_solved` counts in result snapshots.

Some agents initialize their own workspace metadata in the mounted task workspace. Task oracles should grade the required files or repository diff and ignore unrelated harness metadata unless the task explicitly forbids extra files.

## Harness Config Keys

- `backend: docker` enables Docker execution.
- `docker_image` is required.
- `docker_network` defaults to `bridge`; use `none` for offline tasks.
- `docker_workspace` defaults to `/workspace`.
- `docker_mounts` adds extra bind mounts.
- `docker_env_passthrough` passes named host environment variables.
- `docker_memory` and `docker_cpus` set container resource limits.
- `docker_read_only` makes the container root filesystem read-only.
- `docker_tmpfs` mounts writable tmpfs paths.
- `required_env` makes Docker agent harnesses fail before launch if necessary API keys are absent.
- `cli_version` and `version_command` pin and verify CLI versions for Docker agent harnesses.
- `bench_ready: false` marks a harness as not ready for serious comparisons.
