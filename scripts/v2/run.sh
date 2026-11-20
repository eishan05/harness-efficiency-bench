#!/usr/bin/env bash
# Run v2 harnesses on the droplet, one run-suite (or one smoke task) per harness.
#
#   scripts/v2/run.sh smoke RUN_NAME [harness-id ...]   # toy-write-file only
#   scripts/v2/run.sh suite RUN_NAME [harness-id ...]   # the 12 score-facing tasks
#
# Default: every manifest in examples/harnesses/v2. JOBS harnesses run at once
# (default 1). Each harness's results go to runs/v2/RUN_NAME/<harness-id>/; a harness
# whose results already exist is skipped, so a stopped run resumes where it left off.
# Reads OPENCODE_GO_API_KEY from /opt/bench/secrets.env; BENCH_MODEL defaults to
# deepseek-v4.1-flash.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

mode="${1:?usage: run.sh smoke|suite RUN_NAME [harness-id ...]}"
run_name="${2:?usage: run.sh smoke|suite RUN_NAME [harness-id ...]}"
shift 2
case "$mode" in smoke|suite) ;; *) echo "mode must be smoke or suite" >&2; exit 2 ;; esac

if [ -z "${OPENCODE_GO_API_KEY:-}" ] && [ -r /opt/bench/secrets.env ]; then
  set -a; . /opt/bench/secrets.env; set +a
fi
: "${OPENCODE_GO_API_KEY:?OPENCODE_GO_API_KEY is not set}"
export OPENCODE_GO_API_KEY
export BENCH_MODEL="${BENCH_MODEL:-deepseek-v4.1-flash}"
JOBS="${JOBS:-1}"

base="runs/v2/$run_name"
logs="$base/logs"
mkdir -p "$logs"

if [ $# -gt 0 ]; then
  ids=("$@")
else
  ids=()
  for f in examples/harnesses/v2/*.yaml; do ids+=("$(basename "$f" .yaml)"); done
fi

{
  echo "run=$run_name mode=$mode model=$BENCH_MODEL jobs=$JOBS started=$(date -u +%FT%TZ)"
  echo "git=$(git rev-parse --short HEAD 2>/dev/null || echo none) dirty=$(git status --porcelain 2>/dev/null | wc -l)"
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep '^harness-bench/' | sort
} >> "$logs/conditions.txt"
# The exact code that ran, even if it was not committed yet.
git diff HEAD > "$logs/uncommitted.patch" 2>/dev/null || true
git ls-files --others --exclude-standard > "$logs/untracked.txt" 2>/dev/null || true
tar -czf "$logs/untracked.tar.gz" -T "$logs/untracked.txt" 2>/dev/null || true

run_one() {
  local id="$1"
  local out="$base/$id"
  if [ -d "$out/results" ] && [ -n "$(ls -A "$out/results" 2>/dev/null)" ]; then
    echo "$(date -u +%FT%TZ) skip $id (results exist)" >> "$logs/driver.log"
    return 0
  fi
  echo "$(date -u +%FT%TZ) start $id" >> "$logs/driver.log"
  local cmd=(python3 -m harness_efficiency_bench.cli --run-root "$out")
  if [ "$mode" = smoke ]; then
    cmd+=(run-task --task examples/tasks/toy-write-file/task.yaml)
  else
    cmd+=(run-suite --tasks-dir examples/tasks --include-tag score-facing)
  fi
  cmd+=(--harness "examples/harnesses/v2/$id.yaml" --require-docker-isolation)
  # KEEP_WORKSPACE=1 keeps each run's work folder (and the proxy log in it) for debugging.
  [ "${KEEP_WORKSPACE:-0}" = 1 ] || cmd+=(--delete-workspace)
  PYTHONPATH=src "${cmd[@]}" > "$logs/$id.json" 2> "$logs/$id.stderr"
  echo "$(date -u +%FT%TZ) done $id exit=$?" >> "$logs/driver.log"
}
export -f run_one
export base logs mode

printf '%s\n' "${ids[@]}" | xargs -P "$JOBS" -I{} bash -c 'run_one "$@"' _ {}
echo "$(date -u +%FT%TZ) all done" >> "$logs/driver.log"
