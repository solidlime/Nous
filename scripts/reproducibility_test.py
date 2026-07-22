#!/usr/bin/env python3
"""Nous スキル再現性テスト

5つの内臓スキルの自律呼出、画像生成、時間認識をそれぞれ複数回繰り返し、
再現性（同じ条件で同じ結果が出るか）を検証する。

Usage:
    cd /path/to/nous
    python scripts/reproducibility_test.py
"""

import json
import sys
import time
import uuid
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

# ── Constants ───────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:26262"
PERSONA = "herta"
API_URL = f"{BASE_URL}/api/chat/{PERSONA}"
CONFIG_PATH = "data/persona/herta/config.json"
DB_PATH = "data/persona/herta/memory.sqlite"
TEST_INTERVAL = 8
TIMEOUT = 120
JST = timezone(timedelta(hours=9))

# ── Model Detection ─────────────────────────────────────────────────────────

def _read_model() -> str:
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg.get("model", "unknown")
    except Exception:
        return "unknown"

MODEL = _read_model()

# ── SSE Helpers ─────────────────────────────────────────────────────────────

def read_sse_stream(response: Any, timeout: int = TIMEOUT) -> list[dict]:
    """Read SSE stream, return list of parsed JSON events."""
    events: list[dict] = []
    buffer = b""
    start = time.time()
    while True:
        if time.time() - start > timeout:
            events.append({"type": "error", "message": "timeout"})
            break
        chunk = response.read(4096)
        if not chunk:
            break
        buffer += chunk
        while b"\n\n" in buffer:
            block, buffer = buffer.split(b"\n\n", 1)
            for line in block.split(b"\n"):
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded.startswith("data: "):
                    try:
                        ev = json.loads(decoded[6:])
                        events.append(ev)
                        if ev.get("type") in ("done", "error"):
                            return events
                    except json.JSONDecodeError:
                        pass
    return events


def send_chat(message: str) -> list[dict]:
    """Send chat message via API, return SSE events."""
    sid = f"repro-{uuid.uuid4().hex[:8]}"
    body = json.dumps({"message": message, "session_id": sid}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT + 10) as resp:
            return read_sse_stream(resp)
    except Exception as e:
        return [{"type": "error", "message": str(e)}]
