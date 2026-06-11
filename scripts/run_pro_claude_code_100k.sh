#!/usr/bin/env bash
# Claude Code at the 100k injected-context level over the 12 score-facing
# tasks on DeepSeek V4 Pro: does the 100k collapse observed on Flash
# reproduce with a stronger model? Matches the dcurve protocol (900s
# timeouts, CLAUDE_MAX_BUDGET_USD=5).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_BASE="runs/openrouter-deepseek-v4-pro-claude-code-100k-20260611"
MODEL="deepseek/deepseek-v4-pro"
LOGS="$RUN_BASE/logs"
mkdir -p "$LOGS"
for task in python-fix-calculator python-cache-ttl-lru python-cli-subcommands \
            python-csv-ledger-reconcile python-datetime-windowing \
            python-json-config-migration python-markdown-link-normalizer \
            python-path-safety python-plugin-registry toy-write-file \
            harness-stress-log-triage harness-stress-conflicting-specs; do
  env OPENROUTER_MODEL="$MODEL" CLAUDE_MAX_BUDGET_USD=5 PYTHONPATH=src \
    python3 -m harness_efficiency_bench.cli \
    --run-root "$RUN_BASE/claude-code-docker-openrouter" \
    run-task --task "examples/tasks/$task/task.yaml" \
    --perturbation 100k --task-timeout-sec 900 \
    --harness examples/harnesses/claude-code-docker-openrouter.yaml \
    --require-docker-isolation --delete-workspace \
    >> "$LOGS/claude-code.json" 2>> "$LOGS/claude-code.stderr"
  echo "$(date -u +%FT%TZ) claude-code $task exit=$?" >> "$LOGS/driver.log"
done
