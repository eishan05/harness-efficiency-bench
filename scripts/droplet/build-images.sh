#!/usr/bin/env bash
# Build the harness images, tagged harness-bench/<name>:<pinned version>.
#   scripts/droplet/build-images.sh            # every image under docker/
#   scripts/droplet/build-images.sh pi crush   # only these
# The version comes from the Dockerfile's first `ARG <NAME>_VERSION=` line, so the tag
# always matches what the manifests' cli_version checks expect.
set -euo pipefail
cd "$(dirname "$0")/../.."

image_name() {  # directory -> image name (v1 names kept)
  case "$1" in
    antigravity) echo antigravity-cli ;;
    *) echo "$1" ;;
  esac
}

dirs=("$@")
if [ ${#dirs[@]} -eq 0 ]; then
  for d in docker/*/; do d="${d%/}"; dirs+=("${d#docker/}"); done
fi

failed=()
for d in "${dirs[@]}"; do
  [ "$d" = swebench-oracle ] && continue      # built separately for the SWE-bench follow-up
  version="$(sed -n 's/^ARG [A-Z_]*_VERSION=\(.*\)$/\1/p' "docker/$d/Dockerfile" | head -1)"
  [ -n "$version" ] || { echo "no ARG *_VERSION in docker/$d/Dockerfile" >&2; failed+=("$d"); continue; }
  tag="harness-bench/$(image_name "$d"):$version"
  echo "=== $tag"
  if docker build -q -t "$tag" "docker/$d" >"/tmp/build-$d.log" 2>&1; then
    echo "ok $tag"
  else
    echo "FAILED $tag (log: /tmp/build-$d.log)"; tail -20 "/tmp/build-$d.log"; failed+=("$d")
  fi
done
[ ${#failed[@]} -eq 0 ] || { echo "failed: ${failed[*]}" >&2; exit 1; }
