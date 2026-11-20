#!/usr/bin/env bash
# One-time setup of a fresh, disposable Ubuntu 24.04 droplet for v2 runs, as root:
#   ssh root@DROPLET 'bash -s' < scripts/droplet/bootstrap.sh
#
# - Docker (apt), git, Python 3 with PyYAML (the bench's only dependency), rsync.
# - No web server: nothing listens publicly except sshd, and the DigitalOcean cloud
#   firewall (tag harness-bench) admits SSH from one address only.
# - Containers may reach the usage proxy on the docker0 bridge address, but not the
#   droplet's sshd, the DO VPC (10/8), the metadata service (169.254/16) or
#   tailnet-style addresses (100.64/10). They keep normal internet access, which the
#   harnesses need for the model API (through the proxy) and package installs.
set -euo pipefail

# A fresh droplet runs cloud-init (and its apt) first.
cloud-init status --wait >/dev/null 2>&1 || true
while fuser /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock >/dev/null 2>&1; do sleep 5; done

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io git python3 python3-yaml rsync jq curl ca-certificates iptables-persistent
# DigitalOcean's resolver sits in 10/8, which containers may not reach (below), so
# containers and image builds use public resolvers instead.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{"dns": ["1.1.1.1", "8.8.8.8"]}
JSON
systemctl enable docker
systemctl restart docker
docker version --format 'docker {{.Server.Version}}'

# DOCKER-USER sees every packet a container sends off its bridge.
iptables -N DOCKER-USER 2>/dev/null || true
iptables -F DOCKER-USER
for net in 169.254.0.0/16 10.0.0.0/8 100.64.0.0/10; do
  iptables -A DOCKER-USER -d "$net" -j DROP
done
iptables -A DOCKER-USER -j RETURN
# INPUT sees what a container sends to the droplet itself: allow the proxy, not sshd.
for ifc in docker0 'br-+'; do
  iptables -C INPUT -i "$ifc" -p tcp --dport 22 -j DROP 2>/dev/null \
    || iptables -I INPUT -i "$ifc" -p tcp --dport 22 -j DROP
done
netfilter-persistent save

# Runs happen as an unprivileged user with uid 1000: the bench starts containers as
# the host user, and some harnesses (Claude Code's --dangerously-skip-permissions)
# refuse to run as root.
id bench >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash bench
usermod -aG docker bench
mkdir -p /opt/bench
chown -R bench:bench /opt/bench
echo "bootstrap done"
