FROM node:24-bookworm-slim

ARG KILO_VERSION=7.3.40

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@kilocode/cli@${KILO_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/kilo-home
WORKDIR /workspace
