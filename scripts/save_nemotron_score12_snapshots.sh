#!/usr/bin/env bash
# Save snapshot files for the Nemotron free-model score-12 batch.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RUN_BASE="runs/openrouter-nemotron-non-swe-score-12-20260609"
MODEL="nvidia/nemotron-3-ultra-550b-a55b:free"
DATE="2026-06-10"

save_one() {
  local subdir="$1"
  local manifest="$2"
  local suite="$3"
  local out_suffix="$4"
  local extra_env_doc="$5"
  PYTHONPATH=src python3 scripts/save_result_snapshot.py \
    --run-root "$RUN_BASE/$subdir" \
    --out "examples/results/${manifest}-nemotron-non-swe-score-12${out_suffix}-${DATE}.json" \
    --harness "examples/harnesses/$manifest.yaml" \
    --model "$MODEL" \
    --suite "$suite" \
    --tasks-dir examples/tasks \
    --perturbation-mode base-only \
    --oracle-mode "task manifests filtered by score-facing tag" \
    --execution "Docker-isolated $manifest via OpenRouter using $MODEL over the 12 score-facing non-SWE tasks." \
    --command "OPENROUTER_MODEL=$MODEL ${extra_env_doc}PYTHONPATH=src python3 -m harness_efficiency_bench.cli --run-root $RUN_BASE/$subdir run-suite --tasks-dir examples/tasks --include-tag score-facing --harness examples/harnesses/$manifest.yaml --require-docker-isolation --delete-workspace" \
    > /dev/null
  echo "saved ${manifest}-nemotron-non-swe-score-12${out_suffix}-${DATE}.json"
}

save_one aider-docker-openrouter aider-docker-openrouter non-swe-score-12 "" ""
save_one aider-docker-openrouter-architect aider-docker-openrouter non-swe-score-12-architect "-architect" "AIDER_ARCHITECT=1 "
save_one claude-code-docker-openrouter claude-code-docker-openrouter non-swe-score-12 "" ""
save_one codex-docker-openrouter codex-docker-openrouter non-swe-score-12 "" ""
save_one goose-docker-openrouter goose-docker-openrouter non-swe-score-12 "" ""
save_one hermes-agent-docker-openrouter hermes-agent-docker-openrouter non-swe-score-12 "" ""
save_one kilo-docker-openrouter kilo-docker-openrouter non-swe-score-12 "" ""
save_one kimi-code-docker-openrouter kimi-code-docker-openrouter non-swe-score-12 "" ""
save_one nanobot-docker-openrouter nanobot-docker-openrouter non-swe-score-12 "" ""
save_one openclaw-docker-openrouter openclaw-docker-openrouter non-swe-score-12 "" ""
save_one opencode-docker-openrouter opencode-docker-openrouter non-swe-score-12 "" ""
save_one qwen-code-docker-openrouter qwen-code-docker-openrouter non-swe-score-12 "" ""
