#!/usr/bin/env bash
# Four-harness SWE-bench Lite contrast run on DeepSeek V4 Flash with generous
# bounds: does heavy scaffolding buy solve rate on hard, long-horizon tasks?
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_BASE="runs/openrouter-deepseek-v4-flash-swe-contrast-20260610"
MODEL="deepseek/deepseek-v4-flash"
LOGS="$RUN_BASE/logs"
mkdir -p "$LOGS"

run_one() {
  local subdir="$1"
  local manifest="$2"
  local extra_env="${3:-}"
  if [ -d "$RUN_BASE/$subdir/results" ] && [ "$(ls "$RUN_BASE/$subdir/results" 2>/dev/null | wc -l)" -ge 10 ]; then
    echo "=== $(date -u +%FT%TZ) skip $subdir (results exist)" >> "$LOGS/driver.log"
    return 0
  fi
  echo "=== $(date -u +%FT%TZ) start $subdir" >> "$LOGS/driver.log"
  env OPENROUTER_MODEL="$MODEL" $extra_env PYTHONPATH=src \
    python3 -m harness_efficiency_bench.cli \
    --run-root "$RUN_BASE/$subdir" \
    run-suite --tasks-dir examples/tasks/swe-bench-lite-curated-10 \
    --harness "examples/harnesses/$manifest.yaml" \
    --require-docker-isolation --delete-workspace \
    > "$LOGS/$subdir.json" 2> "$LOGS/$subdir.stderr"
  echo "=== $(date -u +%FT%TZ) done $subdir exit=$?" >> "$LOGS/driver.log"
}

run_one aider-docker-openrouter aider-docker-openrouter \
  "AIDER_ARCHITECT=1 AIDER_MAP_TOKENS=2048 AIDER_FILE_MODE=repo-map AIDER_MAX_WALL_TIME=900s"
run_one claude-code-docker-openrouter claude-code-docker-openrouter \
  "CLAUDE_MAX_BUDGET_USD=5"
run_one codex-docker-openrouter codex-docker-openrouter
run_one kilo-docker-openrouter kilo-docker-openrouter \
  "KILO_MAX_WALL_TIME=900s"
echo "=== $(date -u +%FT%TZ) batch complete" >> "$LOGS/driver.log"
