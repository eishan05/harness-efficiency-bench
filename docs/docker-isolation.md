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
