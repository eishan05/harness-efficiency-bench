FROM debian:bookworm-slim

ARG GOOSE_VERSION=1.37.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends bzip2 ca-certificates curl git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN GOOSE_BIN_DIR=/usr/local/bin CONFIGURE=false GOOSE_VERSION="v${GOOSE_VERSION}" \
    bash -c 'curl -fsSL "https://github.com/aaif-goose/goose/releases/download/${GOOSE_VERSION}/download_cli.sh" | bash'

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/goose-home
WORKDIR /workspace
