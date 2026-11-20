FROM node:24-bookworm-slim

ARG CRUSH_VERSION=0.102.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@charmland/crush@${CRUSH_VERSION}" \
    && npm cache clean --force \
    && crush --version | grep -F "${CRUSH_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/crush-home
WORKDIR /workspace
