FROM python:3.12-slim

ARG SWEBENCH_VERSION=4.1.0

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        docker.io \
        docker-cli \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install "swebench==${SWEBENCH_VERSION}"

CMD ["python", "-m", "swebench.harness.run_evaluation", "--help"]
