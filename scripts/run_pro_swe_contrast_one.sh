#!/usr/bin/env bash
# One harness over the curated SWE-bench Lite 10 on DeepSeek V4 Pro,
# matching the Flash contrast protocol. Claude Code's budget cap is raised
# from $5 to $10 because Pro's per-token price is ~4.4x Flash; the cap is
# meant to be generous, not binding.
# Usage: run_pro_swe_contrast_one.sh <subdir> <manifest> [extra_env...]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SUBDIR="$1"; MANIFEST="$2"; shift 2
RUN_BASE="runs/openrouter-deepseek-v4-pro-swe-contrast-20260611"
MODEL="deepseek/deepseek-v4-pro"
LOGS="$RUN_BASE/logs"
mkdir -p "$LOGS"
if [ -d "$RUN_BASE/$SUBDIR/results" ] && [ "$(ls "$RUN_BASE/$SUBDIR/results" 2>/dev/null | wc -l)" -ge 10 ]; then
  echo "=== $(date -u +%FT%TZ) skip $SUBDIR (results exist)" >> "$LOGS/driver.log"
  exit 0
fi
echo "=== $(date -u +%FT%TZ) start $SUBDIR" >> "$LOGS/driver.log"
env OPENROUTER_MODEL="$MODEL" "$@" PYTHONPATH=src \
  python3 -m harness_efficiency_bench.cli \
  --run-root "$RUN_BASE/$SUBDIR" \
  run-suite --tasks-dir examples/tasks/swe-bench-lite-curated-10 \
  --harness "examples/harnesses/$MANIFEST.yaml" \
  --require-docker-isolation --delete-workspace \
  > "$LOGS/$SUBDIR.json" 2> "$LOGS/$SUBDIR.stderr"
echo "=== $(date -u +%FT%TZ) done $SUBDIR exit=$?" >> "$LOGS/driver.log"
