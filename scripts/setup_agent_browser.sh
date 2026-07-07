#!/bin/bash
# Setup agent-browser for MemoryMCP (run at container startup)
set -eo pipefail

# Resolve to absolute path (NOUS_DATA_ROOT may be relative like ./data,
# which breaks symlink resolution when $HOME is /root)
DATA_ROOT=$(realpath "${NOUS_DATA_ROOT:-/opt/nous/data}" 2>/dev/null || echo "/opt/nous/data")
# All agent-browser files (CLI + Chrome cache) live under .agent-browser/
# so they don't pollute the data volume root on the host.
AGENT_DIR="${AGENT_BROWSER_DIR:-$DATA_ROOT/.agent-browser}"
AGENT_BROWSER="$AGENT_DIR/bin/agent-browser"
export PATH="$AGENT_DIR/bin:$PATH"

# ── Step 1: Install agent-browser CLI ──
# Verify the binary actually works (not just exists — host-installed binaries
# may reference node paths from nvm that don't exist in the container).
if AGENT_VERSION=$("$AGENT_BROWSER" --version 2>/dev/null) && [ -n "$AGENT_VERSION" ]; then
    echo "[agent-browser] CLI already available: $AGENT_VERSION"
else
    echo "[agent-browser] Installing CLI to $AGENT_DIR (stale/missing binary)..."
    # Wipe stale npm-installed files only (NOT the entire data volume)
    rm -rf "$AGENT_DIR/bin" "$AGENT_DIR/lib" "$AGENT_DIR/etc" 2>/dev/null || true
    mkdir -p "$AGENT_DIR"
    npm install -g agent-browser --prefix "$AGENT_DIR" 2>&1 | tail -3
    AGENT_VERSION=$("$AGENT_BROWSER" --version 2>/dev/null)
    echo "[agent-browser] CLI installed: $AGENT_VERSION"
fi

# ── Step 2: Persist Chrome cache to volume via symlink ──
# agent-browser stores Chrome under $HOME/.agent-browser/browsers,
# which is lost on container restart. Symlink to the data volume so
# Chrome survives restarts and doesn't re-download.
AGENT_HOME="$DATA_ROOT/.agent-browser"
if [ ! -L "$HOME/.agent-browser" ]; then
    mkdir -p "$AGENT_HOME"
    if [ -d "$HOME/.agent-browser" ] && [ ! -L "$HOME/.agent-browser" ]; then
        mv "$HOME/.agent-browser"/* "$AGENT_HOME/" 2>/dev/null || true
        rm -rf "$HOME/.agent-browser"
    fi
    ln -sfn "$AGENT_HOME" "$HOME/.agent-browser"
fi

# ── Step 3: Configure --no-sandbox for Chrome in Docker ──
# Chrome's SUID sandbox requires unprivileged user namespaces which are
# typically unavailable in Docker. --no-sandbox is safe here because the
# container itself provides isolation.
# Chrome system dependencies (libcairo2, libgtk-3-0, etc.) are pre-installed
# in the Dockerfile build stage — no runtime apt-get needed.
AGENT_CONFIG="$AGENT_DIR/config.json"
if [ ! -f "$AGENT_CONFIG" ]; then
    mkdir -p "$(dirname "$AGENT_CONFIG")"
    echo '{"args": "--no-sandbox"}' > "$AGENT_CONFIG"
    echo "[agent-browser] --no-sandbox configured (Docker mode)"
fi

# ── Step 4: Ensure Chrome browser is installed (idempotent, background) ──
# Run Chrome download in background with low CPU/IO priority to avoid
# starving the MCP server during first-time setup (~200MB download).
AGENT_LOG="$AGENT_DIR/install.log"
echo "[agent-browser] Chrome install starting in background (log: $AGENT_LOG)..."
(
    nice -n 19 ionice -c 3 "$AGENT_BROWSER" install
    # Clean up old Chrome versions (keep only the latest)
    CHROME_DIR="$AGENT_HOME/browsers"
    if [ -d "$CHROME_DIR" ]; then
        OLD=$(ls -1dt "$CHROME_DIR"/chrome-* 2>/dev/null | tail -n +2)
        if [ -n "$OLD" ]; then
            echo "[agent-browser] Removing old Chrome: $OLD" >> "$AGENT_LOG"
            rm -rf "$OLD"
        fi
    fi
) >> "$AGENT_LOG" 2>&1 &
# Record PID so server can poll readiness if needed
echo $! > /tmp/agent-browser-install.pid

echo "[agent-browser] Server starting (Chrome will be ready shortly)..."
echo "[agent-browser] version: $($AGENT_BROWSER --version)"

exec "$@"
