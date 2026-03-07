#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[Nous] .venv が見つからないため uv sync を実行します..."
    uv sync
fi

echo "[Nous] サーバーを起動します..."
.venv/bin/python main.py
