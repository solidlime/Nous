# MCP Hub - MCPプロキシ + 管理Web UI
# python:3.12-slim + Node.js LTS + ビルドツール
# 複数MCPサーバーを集約し、統合エンドポイントとして再公開

FROM python:3.12-slim

ENV APP_HOME=/opt/mcp-hub \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    TZ=Asia/Tokyo

WORKDIR ${APP_HOME}

# Node.js LTS + ビルドツール (MCP サーバー実行・native addon ビルド用)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    wget \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | \
    gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Puppeteer 用 Chromium (headless browser automation)
ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    chromium \
    chromium-sandbox \
    && rm -rf /var/lib/apt/lists/*

# Python: uv パッケージマネージャ
RUN pip install --no-cache-dir uv

# アプリケーションコード
COPY pyproject.toml ${APP_HOME}/
COPY src/ ${APP_HOME}/src/

# 依存関係インストール
RUN cd ${APP_HOME} && uv pip install --system -e .

# データディレクトリ
RUN mkdir -p ${APP_HOME}/data

# 非rootユーザー
RUN useradd --create-home --shell /bin/bash mcp-hub && \
    chown -R mcp-hub:mcp-hub ${APP_HOME}

USER mcp-hub

EXPOSE 26263

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:26263/admin/api/health || exit 1

CMD ["python", "-m", "mcp_hub.main"]
