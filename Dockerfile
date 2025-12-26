# =============================================================================
# iHIM - EdgeFlow AI Command Center
# Multi-stage Docker build for optimized image size
# =============================================================================

# Stage 1: Build dependencies
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first (better layer caching)
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# Stage 2: Production image
FROM python:3.12-slim as production

# Labels
LABEL org.opencontainers.image.title="iHIM"
LABEL org.opencontainers.image.description="EdgeFlow AI Command Center"
LABEL org.opencontainers.image.version="1.0.0"

# Create non-root user for security
RUN groupadd --gid 1000 ihim && \
    useradd --uid 1000 --gid ihim --shell /bin/bash --create-home ihim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=ihim:ihim api/ ./api/
COPY --chown=ihim:ihim actions/ ./actions/
COPY --chown=ihim:ihim team/ ./team/
COPY --chown=ihim:ihim ui/ ./ui/

# Create data directory with proper permissions
RUN mkdir -p /app/data && chown -R ihim:ihim /app/data

# Environment configuration (overridable)
ENV IHIM_HOST=${IHIM_HOST:-0.0.0.0}
ENV IHIM_PORT=${IHIM_PORT:-7777}
ENV IHIM_RELOAD=${IHIM_RELOAD:-false}
ENV IHIM_LOG_LEVEL=${IHIM_LOG_LEVEL:-info}
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER ihim

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${IHIM_PORT}/api/health')" || exit 1

# Expose port (configurable via IHIM_PORT)
EXPOSE 7777

# Start command
CMD ["sh", "-c", "uvicorn api.main:app --host ${IHIM_HOST} --port ${IHIM_PORT} --log-level ${IHIM_LOG_LEVEL}"]
