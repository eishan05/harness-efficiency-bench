FROM debian:bookworm-slim

ARG ANTIGRAVITY_CLI_VERSION=1.0.6

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        dbus \
        git \
        libsecret-1-0 \
        libsecret-tools \
        python3 \
        ripgrep \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/install-antigravity.sh \
    && bash /tmp/install-antigravity.sh --dir /usr/local/bin \
    && rm -f /tmp/install-antigravity.sh \
    && agy --version | grep -F "${ANTIGRAVITY_CLI_VERSION}"

RUN useradd --create-home --home-dir /antigravity-home --shell /bin/bash --uid 1000 bench \
    && mkdir -p /workspace /antigravity-home \
    && chown -R bench:bench /workspace /antigravity-home

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

USER bench
ENV HOME=/antigravity-home
WORKDIR /workspace
