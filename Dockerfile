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

# Create non-root user for running the application
RUN groupadd --gid 1000 tfp && \
    useradd --uid 1000 --gid tfp --shell /bin/bash --create-home tfp

# Copy installed packages from builder and relocate for non-root user
COPY --from=builder /root/.local /home/tfp/.local
RUN chown -R tfp:tfp /home/tfp/.local

# Make sure scripts in .local are usable
ENV PATH=/home/tfp/.local/bin:$PATH

# Copy application code
COPY tfp-foundation-protocol/tfp_demo/ ./tfp_demo/
COPY tfp-foundation-protocol/tfp_client/ ./tfp_client/
COPY tfp-foundation-protocol/tfp_broadcaster/ ./tfp_broadcaster/
COPY tfp-foundation-protocol/tfp_cli/ ./tfp_cli/
COPY tfp-foundation-protocol/tfp_common/ ./tfp_common/
COPY tfp-foundation-protocol/tfp_simulator/ ./tfp_simulator/
COPY tfp-foundation-protocol/demo/ ./demo/

# Environment variables
ENV PYTHONPATH=/app
ENV TFP_DB_PATH=/data/tfp.db
ENV PORT=8000

# Create data directory and set ownership
RUN mkdir -p /data && chown tfp:tfp /data

# Switch to non-root user
USER tfp

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the server
CMD ["python", "-m", "uvicorn", "tfp_demo.server:app", "--host", "0.0.0.0", "--port", "8000"]
