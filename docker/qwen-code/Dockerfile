FROM node:24-bookworm-slim

ARG QWEN_CODE_VERSION=0.17.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@qwen-code/qwen-code@${QWEN_CODE_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/qwen-home
WORKDIR /workspace
