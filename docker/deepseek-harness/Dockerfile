FROM python:3.12-slim-bookworm

# DeepSeek Harness (dsh), DeepSeek's own agent harness. The Python SDK wheel ships the
# native runtime and the `dsh` command, so no Node.js is needed. Developer preview:
# only release candidates are published.
ARG DEEPSEEK_HARNESS_VERSION=0.2.2rc2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir "deepseek-harness-sdk==${DEEPSEEK_HARNESS_VERSION}"

COPY run-agent minimal.py bench.patch.yml headless-model.patch.yml /opt/harness/
RUN chmod +x /opt/harness/run-agent

ENV HOME=/dsh-home \
    DSH_HOME=/dsh-home/.dsh
WORKDIR /workspace
