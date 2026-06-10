#!/usr/bin/env bash
# 100k-payload transmission-fidelity probe for one harness config:
# three representative tasks at the 100k injected-context level.
# Usage: run_fidelity_100k.sh <subdir> <manifest> [extra_env...]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SUBDIR="$1"; MANIFEST="$2"; shift 2
RUN_BASE="runs/openrouter-deepseek-v4-flash-fidelity-100k-20260610"
mkdir -p "$RUN_BASE/logs"
for task in python-fix-calculator python-cli-subcommands toy-write-file; do
  env OPENROUTER_MODEL=deepseek/deepseek-v4-flash "$@" PYTHONPATH=src \
    python3 -m harness_efficiency_bench.cli \
    --run-root "$RUN_BASE/$SUBDIR" \
    run-task --task "examples/tasks/$task/task.yaml" \
    --perturbation 100k --task-timeout-sec 900 \
    --harness "examples/harnesses/$MANIFEST.yaml" \
    --require-docker-isolation --delete-workspace \
    >> "$RUN_BASE/logs/$SUBDIR.json" 2>> "$RUN_BASE/logs/$SUBDIR.stderr"
  echo "$(date -u +%FT%TZ) $SUBDIR $task exit=$?" >> "$RUN_BASE/logs/driver.log"
done
