#!/usr/bin/env bash
# Sequential Nemotron free-model batch over the 12 score-facing non-SWE tasks,
# one run-suite per harness, matching the DeepSeek V4 Flash score-12 protocol.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_BASE="runs/openrouter-nemotron-non-swe-score-12-20260609"
MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"
LOGS="$RUN_BASE/logs"
mkdir -p "$LOGS"

run_one() {
  local subdir="$1"
  local manifest="$2"
  local extra_env="${3:-}"
  if [ -d "$RUN_BASE/$subdir/results" ] && [ -n "$(ls "$RUN_BASE/$subdir/results" 2>/dev/null)" ]; then
    echo "=== $(date -u +%FT%TZ) skip $subdir (results exist)" >> "$LOGS/driver.log"
    return 0
  fi
  echo "=== $(date -u +%FT%TZ) start $subdir" >> "$LOGS/driver.log"
  env OPENROUTER_MODEL="$MODEL" $extra_env PYTHONPATH=src \
    python3 -m harness_efficiency_bench.cli \
    --run-root "$RUN_BASE/$subdir" \
    run-suite --tasks-dir examples/tasks --include-tag score-facing \
    --harness "examples/harnesses/$manifest.yaml" \
    --require-docker-isolation --delete-workspace \
    > "$LOGS/$subdir.json" 2> "$LOGS/$subdir.stderr"
  echo "=== $(date -u +%FT%TZ) done $subdir exit=$?" >> "$LOGS/driver.log"
}

run_one aider-docker-openrouter aider-docker-openrouter
run_one aider-docker-openrouter-architect aider-docker-openrouter "AIDER_ARCHITECT=1"
run_one claude-code-docker-openrouter claude-code-docker-openrouter
run_one codex-docker-openrouter codex-docker-openrouter
run_one goose-docker-openrouter goose-docker-openrouter
run_one hermes-agent-docker-openrouter hermes-agent-docker-openrouter
run_one kilo-docker-openrouter kilo-docker-openrouter
run_one kimi-code-docker-openrouter kimi-code-docker-openrouter
run_one nanobot-docker-openrouter nanobot-docker-openrouter
run_one openclaw-docker-openrouter openclaw-docker-openrouter
run_one opencode-docker-openrouter opencode-docker-openrouter
run_one qwen-code-docker-openrouter qwen-code-docker-openrouter
echo "=== $(date -u +%FT%TZ) batch complete" >> "$LOGS/driver.log"
