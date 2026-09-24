# The workspace the learner's editor attaches to (ADR-019).
#
# This container is on the stack's Compose network, which is the whole point: a terminal here
# resolves `wom.aquaflux.internal` and does not resolve the stack on `localhost`. A browser on the
# learner's own machine reaches the stack through forwarded ports instead. That rule is stated
# once in labs/README.md and every handout follows it.
#
# python:3.12-slim publishes linux/amd64 and linux/arm64. Every image in this stack must.

FROM python:3.12-slim

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        less \
        libpq-dev \
        postgresql-client \
        procps \
        ssh \
        sudo \
        unzip \
        uuid-runtime \
    && rm -rf /var/lib/apt/lists/*

# What the labs import. requests is a-02's worked tier verbatim; psycopg and pyyaml are b-01's;
# mcp is the SDK c-02 writes its server with, and it is here rather than in a per-lab
# requirements file because installing it would be setup, and setup is never the task. The
# OpenTelemetry SDK and its OTLP/HTTP exporter are what the agents in labs/stack/agent/ write
# their spans with, and what d-04's handout has the learner add two lines to. temporalio is the
# workflow engine's SDK: e-03's worker runs in this container, so it is installed here and not
# in an image of its own (labs/stack/docker-compose.yml, profile workflow, says why).
RUN pip install --no-cache-dir \
        requests==2.32.5 \
        httpx==0.28.1 \
        pyyaml==6.0.2 \
        psycopg[binary]==3.2.10 \
        pytest==8.4.2 \
        mcp==2.2.0 \
        opentelemetry-sdk==1.44.0 \
        opentelemetry-exporter-otlp-proto-http==1.44.0 \
        temporalio==1.33.0

# The policy engine's command line, for `opa test policy/`, which d-03 and f-01 run in this
# terminal. The same version as the `policy` service, pinned in labs/stack/images.yml, and
# verified against the published checksum so a tampered download fails the build rather than
# a lab. dpkg's architecture names match the download names: amd64 on Intel, arm64 on an
# M-series Mac.
ARG OPA_VERSION=1.20.2
RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/opa "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_${arch}_static" \
    && curl -fsSL -o /tmp/opa.sha256 "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_${arch}_static.sha256" \
    && (cd /tmp && sed "s/ .*/  opa/" opa.sha256 | sha256sum -c -) \
    && install -m 0755 /tmp/opa /usr/local/bin/opa \
    && rm -f /tmp/opa /tmp/opa.sha256

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# `aqx`, the stack's small wrapper, and the lab scripts are on the path. f-01 names `aqx` once.
ENV PATH="/workspaces/agentic-integration-academy/labs/stack/bin:${PATH}"

USER $USERNAME
WORKDIR /workspaces/agentic-integration-academy
