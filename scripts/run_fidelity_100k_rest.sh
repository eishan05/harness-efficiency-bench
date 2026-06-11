#!/usr/bin/env bash
# Extend the 100k transmission-fidelity probe from the 3 representative tasks
# to the full score-12 suite: runs the 9 remaining tasks for one harness
# config into the same run base as run_fidelity_100k.sh.
# Usage: run_fidelity_100k_rest.sh <subdir> <manifest> [extra_env...]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SUBDIR="$1"; MANIFEST="$2"; shift 2
RUN_BASE="runs/openrouter-deepseek-v4-flash-fidelity-100k-20260610"
mkdir -p "$RUN_BASE/logs"
for task in python-cache-ttl-lru python-csv-ledger-reconcile \
            python-datetime-windowing python-json-config-migration \
            python-markdown-link-normalizer python-path-safety \
            python-plugin-registry harness-stress-log-triage \
            harness-stress-conflicting-specs; do
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
