FROM python:3.12-slim-bookworm

ARG AIDER_VERSION=0.86.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "aider-chat==${AIDER_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/aider-home
WORKDIR /workspace
