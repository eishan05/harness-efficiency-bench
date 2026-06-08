FROM node:22-bookworm-slim

ARG CODEX_VERSION=0.137.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git python-is-python3 python3 python3-pip python3-venv ripgrep xxd \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
ENTRYPOINT []
