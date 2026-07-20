# Multi-stage build for Nous with FastMCP - Optimized
# Build stage: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Build dependencies not needed for AMD64 (pre-built manylinux wheels).
# For ARM64, install gcc/g++ if sudachipy fails to build:
#   RUN apt-get update && apt-get install -y --no-install-recommends gcc g++

# Copy requirements (production-only — dev deps are in requirements-dev.txt)
COPY requirements-prod.txt ./

# Install Python dependencies (ONNX Runtime replaces PyTorch — no torch needed)
RUN pip install --no-cache-dir --no-build-isolation -r requirements-prod.txt

# Runtime stage: Copy only necessary files
FROM python:3.12-slim

ENV APP_HOME=/app \
    NOUS_DATA_ROOT=/opt/nous \
    HF_HOME=/opt/nous/cache/huggingface \
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
# Clean up Python cache and unnecessary files to reduce image size
RUN find /usr/local/lib/python3.12/site-packages \
    \( -type d \( -name __pycache__ -o -name tests -o -name test \) -prune -exec rm -rf {} + \) , \
    \( -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.c' -o -name '*.h' \) -delete \) \
    2>/dev/null; true && \
    python3.12 -m pip uninstall -y pip 2>/dev/null || true

# Copy application code (v2: memory_mcp package only)
COPY nous/ ${APP_HOME}/nous/
COPY pyproject.toml ${APP_HOME}/

# Copy default global skills (auto-memory, auto-self-portrait, goal-coach, mood-sync, recall-weaver)
# Exclude runtime sqlite files — the app creates them at startup
COPY data/skills/auto-memory/ /opt/nous/skills/auto-memory/
COPY data/skills/auto-self-portrait/ /opt/nous/skills/auto-self-portrait/
COPY data/skills/goal-coach/ /opt/nous/skills/goal-coach/
COPY data/skills/mood-sync/ /opt/nous/skills/mood-sync/
COPY data/skills/recall-weaver/ /opt/nous/skills/recall-weaver/

# Create non-root user
RUN useradd --create-home --shell /bin/bash nous

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
