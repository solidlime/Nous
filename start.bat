@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo [Nous] .venv が見つからないため uv sync を実行します...
    uv sync
    if errorlevel 1 (
        echo [ERROR] uv sync 失敗。uv がインストールされているか確認してください。
        pause
        exit /b 1
    )
)

echo [Nous] サーバーを起動します...
.venv\Scripts\python.exe main.py

pause
