# TFP Foundation Protocol - Demo Node
# Multi-stage build for production deployment

FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY tfp-foundation-protocol/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY tfp-foundation-protocol/tfp_demo/ ./tfp_demo/
COPY tfp-foundation-protocol/tfp_client/ ./tfp_client/
COPY tfp-foundation-protocol/tfp_broadcaster/ ./tfp_broadcaster/
COPY tfp-foundation-protocol/tfp_cli/ ./tfp_cli/
COPY tfp-foundation-protocol/tfp_common/ ./tfp_common/
COPY tfp-foundation-protocol/tfp_simulator/ ./tfp_simulator/

# Environment variables
ENV PYTHONPATH=/app
ENV TFP_DB_PATH=/data/tfp.db
ENV PORT=8000

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the server
CMD ["sh", "-c", "mkdir -p /data && python -m uvicorn tfp_demo.server:app --host 0.0.0.0 --port 8000"]
