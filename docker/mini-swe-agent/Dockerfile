FROM python:3.12-slim-bookworm

ARG MINI_SWE_AGENT_VERSION=2.4.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "mini-swe-agent==${MINI_SWE_AGENT_VERSION}"

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/mini-home
WORKDIR /workspace
