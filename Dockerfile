# syntax=docker/dockerfile:1
# The Foundation Protocol - Demo Node & Workshop Environment
# Multi-stage build for production and developer workshop deployment

# -----------------------------------------------------------------------------
# Base stage: minimal Python runtime and build tools
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# Production stage: Lean runtime, non-root user tfp, copies runtime code,
# installs ONLY requirements.txt (zero test/dev tools).
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS production

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/tfp-foundation-protocol \
    TFP_DB_PATH=/data/tfp.db \
    PORT=8000

# Create non-root user for running the application
RUN groupadd --gid 1000 tfp && \
    useradd --uid 1000 --gid tfp --shell /bin/bash --create-home tfp

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY pure production requirements (zero pytest, zero httpx, zero test tools)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy runtime application code
COPY tfp-foundation-protocol/ /app/tfp-foundation-protocol/
COPY tfp_cli/ /app/tfp_cli/
COPY tfp_core/ /app/tfp_core/
COPY tfp_simulator/ /app/tfp_simulator/
COPY tfp_transport/ /app/tfp_transport/
COPY tfp_security/ /app/tfp_security/
COPY tfp_plugins/ /app/tfp_plugins/
COPY tfp_plugin_sdk/ /app/tfp_plugin_sdk/
COPY tfp_ui/ /app/tfp_ui/

# Set up data directory and permissions
RUN mkdir -p /data && chown -R tfp:tfp /data /app

USER tfp

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "uvicorn", "tfp_demo.server:app", "--host", "0.0.0.0", "--port", "8000"]

# -----------------------------------------------------------------------------
# Workshop-Dev stage: Developer tooling, test suites, ast-grep, ruff, mypy,
# hypothesis, volume-mounted live workspace
# -----------------------------------------------------------------------------
FROM base AS workshop-dev

WORKDIR /workspace

# Copy requirements
COPY requirements.txt /workspace/requirements.txt
COPY requirements-dev.txt /workspace/requirements-dev.txt

# Install all developer and testing tools
RUN pip install --no-cache-dir -r /workspace/requirements-dev.txt

# Set environment
ENV PYTHONPATH=/workspace:/workspace/tfp-foundation-protocol
ENV TFP_DB_PATH=/workspace/pib.db

# Keep container alive for interactive development and automated testing
CMD ["sleep", "infinity"]
