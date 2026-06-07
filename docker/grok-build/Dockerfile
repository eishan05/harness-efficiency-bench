FROM debian:bookworm-slim

ARG GROK_BUILD_VERSION=0.2.33

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN GROK_BIN_DIR=/usr/local/bin GROK_BUILD_VERSION="${GROK_BUILD_VERSION}" \
    bash -c 'curl -fsSL https://x.ai/cli/install.sh | bash -s "${GROK_BUILD_VERSION}"'

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/grok-home
WORKDIR /workspace
