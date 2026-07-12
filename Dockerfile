# Multi-stage build for Nous with FastMCP - Optimized
# Build stage: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (production-only — dev deps are in requirements-dev.txt)
COPY requirements-prod.txt ./

# Install Python dependencies (ONNX Runtime replaces PyTorch — no torch needed)
RUN pip install --no-cache-dir uv && \
    uv pip install --system -r requirements-prod.txt && \
    uv cache clean

# Runtime stage: Copy only necessary files
FROM python:3.12-slim

ENV APP_HOME=/opt/nous \
    NOUS_DATA_ROOT=/opt/nous/data \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    TZ=UTC

# Set working directory
WORKDIR ${APP_HOME}

# Install only runtime dependencies (curl for healthcheck, tzdata for timezone)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Clean up Python cache and unnecessary files to reduce image size
RUN find /usr/local/lib/python3.12/site-packages -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12/site-packages -type d -name tests -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12/site-packages -type d -name test -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12/site-packages -type f -name '*.pyc' -delete && \
    find /usr/local/lib/python3.12/site-packages -type f -name '*.pyo' -delete && \
    find /usr/local/lib/python3.12/site-packages -type f -name '*.c' -delete && \
    find /usr/local/lib/python3.12/site-packages -type f -name '*.h' -delete

# Copy application code (v2: memory_mcp package only)
COPY nous/ ${APP_HOME}/nous/
COPY pyproject.toml ${APP_HOME}/

# Create data directory under APP_HOME
RUN mkdir -p ${APP_HOME}/data

# Create non-root user
RUN useradd --create-home --shell /bin/bash nous && \
    chown -R nous:nous ${APP_HOME}/data

# Expose FastMCP HTTP port
EXPOSE 26262

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:26262/health || exit 1

CMD ["python", "-m", "nous.main"]

# Notes:
# - Development tip: place environment overrides in a top-level `.env` (or use Compose `env_file:`)
#   and add to `.gitignore` to avoid checking secrets into git.
# - `docker-compose.yml` has an `env_file:` line so `.env` values will be injected into the container.
