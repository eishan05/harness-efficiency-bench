FROM node:24-bookworm-slim

ARG KIMI_CODE_VERSION=0.11.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@moonshot-ai/kimi-code@${KIMI_CODE_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/kimi-home
WORKDIR /workspace
