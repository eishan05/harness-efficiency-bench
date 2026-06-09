FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.114

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        python3 \
        ripgrep \
        xxd \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /claude-home /workspace \
    && chown -R node:node /claude-home /workspace

WORKDIR /workspace

USER node
ENV HOME=/claude-home

ENTRYPOINT []
