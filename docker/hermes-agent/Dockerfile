FROM python:3.12-slim-bookworm

ARG HERMES_AGENT_VERSION=0.16.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "hermes-agent==${HERMES_AGENT_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/hermes-home
WORKDIR /workspace
