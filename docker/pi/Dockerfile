FROM node:24-bookworm-slim

ARG PI_VERSION=1.6.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && npm cache clean --force \
    && test "$(HOME=/tmp pi --version)" = "${PI_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/pi-home
WORKDIR /workspace
