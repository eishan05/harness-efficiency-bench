FROM node:24-bookworm-slim

ARG OPENCLAW_VERSION=2026.6.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/openclaw-home
WORKDIR /workspace
