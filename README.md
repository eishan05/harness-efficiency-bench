# Harness Efficiency Bench

Benchmark coding-agent harnesses on token efficiency, context growth, tool-output retention, cost, and solve rate.

The v1 scaffold is designed around small task manifests and pluggable harness adapters. It can run a toy benchmark immediately, and it includes adapter entry points for Codex, Claude Code, Antigravity, Qwen Code, mini-swe-agent, nanobot, and generic command-line harnesses.

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

## Adding Harnesses

Start with `examples/harnesses/generic-cli.yaml` if the harness can run one command and exit. Use a first-class adapter when the harness emits structured events or has an SDK. See `docs/adding-harnesses.md`.
