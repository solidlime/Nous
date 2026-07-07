# Multi-stage build for Nous with FastMCP - Optimized
# Build stage: Install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt ./

# Install PyTorch CPU version first (to avoid CUDA dependencies)
# Use PyTorch's CPU-only index to prevent CUDA packages
RUN pip install --no-cache-dir \
    torch \
    torchvision \
    torchaudio \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Runtime stage: Copy only necessary files
FROM python:3.12-slim

ENV APP_HOME=/opt/nous \
    NOUS_DATA_ROOT=/opt/nous/data \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    TZ=Asia/Tokyo

# Set working directory
WORKDIR ${APP_HOME}

# Install only runtime dependencies (curl for healthcheck, tzdata for timezone)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    # OCR用。不要なら削除可
    tesseract-ocr \
    tesseract-ocr-jpn \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Add Node.js for agent-browser
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get install -y --no-install-recommends \
        libnspr4 libnss3 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libasound2 \
        libcairo2 libgtk-3-0 libpangocairo-1.0-0 libdbus-1-3 \
        libfontconfig1 libfreetype6 \
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
    find /usr/local/lib/python3.12/site-packages -type f -name '*.h' -delete && \
    rm -rf /usr/local/lib/python3.12/site-packages/pip /usr/local/lib/python3.12/site-packages/setuptools

# Copy application code (v2: memory_mcp package only)
COPY nous/ ${APP_HOME}/nous/
COPY pyproject.toml ${APP_HOME}/

# Create data directory under APP_HOME
RUN mkdir -p ${APP_HOME}/data

# Copy agent-browser setup script for first-run installation
COPY scripts/setup_agent_browser.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/setup_agent_browser.sh

# Copy sandbox Dockerfile for on-demand image building
COPY Dockerfile.sandbox ${APP_HOME}/

# Create non-root user
RUN useradd --create-home --shell /bin/bash nous && \
    chown -R nous:nous ${APP_HOME}/data

# Expose FastMCP HTTP port
EXPOSE 26262

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:26262/health || exit 1

# Run agent-browser setup on startup, then launch the MCP server
ENTRYPOINT ["/usr/local/bin/setup_agent_browser.sh"]
CMD ["python", "-m", "nous.main"]

# Switch to non-root user
USER nous

# Notes:
# - Development tip: place environment overrides in a top-level `.env` (or use Compose `env_file:`)
#   and add to `.gitignore` to avoid checking secrets into git.
# - `docker-compose.yml` has an `env_file:` line so `.env` values will be injected into the container.
