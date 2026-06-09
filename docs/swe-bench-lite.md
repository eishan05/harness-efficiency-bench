# SWE-bench Lite Integration

This repository includes a curated 10-task SWE-bench Lite subset under:

```text
examples/tasks/swe-bench-lite-curated-10/
```

The subset is intentionally small for first serious runs. It covers Django, SymPy, Matplotlib, pytest, and xarray while reusing repo/version families to keep Docker image pulls and build cache cost manageable.

Regenerate the task manifests from Hugging Face:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli import-swe-bench-lite
```

Run one SWE-bench task with a Docker-isolated harness:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli run-task \
  --task examples/tasks/swe-bench-lite-curated-10/django__django-11905/task.yaml \
  --harness examples/harnesses/codex-docker-isolated.yaml \
  --require-docker-isolation
```

Build the Dockerized SWE-bench oracle image before running SWE-bench oracles:

```bash
docker build -t harness-bench/swebench-oracle:4.1.0 docker/swebench-oracle
```

SWE-bench task workspaces are cloned from GitHub at the instance `base_commit`. By default the runner keeps local Git mirrors in `.cache/harness-bench/repos`; override with `--repo-cache <path>` or disable with `--no-repo-cache`.

The `swe_bench` oracle writes a one-line prediction JSONL from the workspace diff and invokes the official evaluator inside `harness-bench/swebench-oracle:4.1.0`. The evaluator container mounts `/var/run/docker.sock`, so it does not install `swebench` on the host but it does create official SWE-bench Docker images on the host Docker daemon:

```bash
docker run --rm \
  --user <host-uid>:<host-gid> \
  --group-add <docker-socket-gid> \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v <absolute-run>/swebench_eval:<absolute-run>/swebench_eval \
  -w <absolute-run>/swebench_eval \
  harness-bench/swebench-oracle:4.1.0 \
  python -m swebench.harness.run_evaluation ...
```

The oracle supports `arch: auto|x86_64|arm64` and `namespace: auto|swebench|none`. On `x86_64`, `auto` uses the official remote `swebench/*` eval images. On `arm64`, `auto` builds local `sweb.*arm64*` images because the official remote eval images are amd64-only and otherwise fail with an `exec format error`. Some upstream SWE-bench environments still may not solve on ARM; for example, xarray environments that require `cdms2` do not currently build on `linux-aarch64`.

Host-mode evaluation is still available by setting `oracle.backend: host` and installing `python3 -m pip install -e '.[swebench]'`, but Docker mode is the default for curated SWE-bench Lite manifests.

The official evaluator creates Docker images with `sweb.*` repositories. Ordinary cleanup keeps those caches because rebuilding them is expensive. Remove them explicitly with:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli cleanup-docker --include-swebench --force
```

This repository can also export SWE-bench-style predictions from Git-initialized task workspaces:

```bash
PYTHONPATH=src python3 -m harness_efficiency_bench.cli export-predictions \
  --out predictions.jsonl
```

The current starter suite is intentionally local and cheap:

- `python-fix-calculator` exercises ordinary unit-test-driven bug fixing.
- `harness-stress-log-triage` exercises log reading and tool-output-heavy context pressure.
- `toy-write-file` exercises deterministic smoke runs and context-bloat perturbations.

Use these tasks to validate harness adapters, isolation, cleanup, and metric coverage before spending on SWE-bench Lite runs.

## Saved Smoke Results

The local subscription Codex no-oracle smoke over all 10 curated tasks is saved in:

```text
examples/results/codex-local-swe-bench-lite-curated-10-smoke-2026-06-08.json
```

Use this snapshot for quick Codex A/B/C metric comparisons without rerunning the hour-long smoke. It records harness completion with `oracle: none`; it is not an official SWE-bench solve-rate result.
