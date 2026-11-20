#!/usr/bin/env bash
# Copy this working tree to the droplet (/opt/bench/hb), leaving its runs/ alone.
#   scripts/droplet/push.sh root@DROPLET_IP
set -euo pipefail
host="${1:?usage: push.sh root@DROPLET_IP}"
cd "$(dirname "$0")/../.."
rsync -az --delete --exclude runs/ --exclude results/ --exclude __pycache__/ ./ "$host:/opt/bench/hb/"
ssh -n "$host" 'chown -R bench:bench /opt/bench/hb'
