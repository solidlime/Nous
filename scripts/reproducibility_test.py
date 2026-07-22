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


# ── Event Analysis ──────────────────────────────────────────────────────────

def collect_tool_calls(events: list[dict]) -> list[dict]:
    """Extract all tool_call events from SSE event list."""
    return [e for e in events if e.get("type") == "tool_call"]


def get_text_response(events: list[dict]) -> str:
    """Concatenate text_delta content."""
    return "".join(e.get("content", "") for e in events
                   if e.get("type") == "text_delta")


def check_invoke_skill_chain(
    events: list[dict], expected_skill: str, expected_tool: str,
) -> dict:
    """Check if invoke_skill → expected_tool chain occurred."""
    result = {
        "invoke_skill_called": False,
        "invoke_skill_args": None,
        "target_tool_called": False,
        "target_tool_args": None,
        "error": None,
    }
    for ev in events:
        t = ev.get("type", "")
        if t == "error":
            result["error"] = ev.get("message", "")
        elif t == "tool_call":
            name = ev.get("name", "")
            inp = ev.get("input", {})
            if name == "invoke_skill":
                skill_name = inp.get("name", "") if isinstance(inp, dict) else ""
                if skill_name == expected_skill:
                    result["invoke_skill_called"] = True
                    result["invoke_skill_args"] = inp
            elif name == expected_tool:
                result["target_tool_called"] = True
                result["target_tool_args"] = inp
    return result


def check_tool_called(events: list[dict], tool_name: str) -> bool:
    """Simple check: was a given tool called at least once?"""
    return any(
        ev.get("type") == "tool_call" and ev.get("name") == tool_name
        for ev in events
    )


# ── Emotion Detection for Test 3 ────────────────────────────────────────────

EMOTION_KEYWORDS = [
    "sadness", "loneliness", "disappointment",
    "sad", "lonely", "disappointed",
]


def check_emotion_in_update_context(events: list[dict]) -> dict:
    """Check if update_context was called with sadness/loneliness/disappointment."""
    result = {
        "invoke_mood_sync_called": False,
        "update_context_called": False,
        "emotion_found": False,
        "emotion_value": None,
        "error": None,
    }
    for ev in events:
        t = ev.get("type", "")
        if t == "error":
            result["error"] = ev.get("message", "")
        elif t == "tool_call":
            name = ev.get("name", "")
            inp = ev.get("input", {})
            if name == "invoke_skill" and isinstance(inp, dict) and inp.get("name") == "mood-sync":
                result["invoke_mood_sync_called"] = True
            elif name == "update_context":
                result["update_context_called"] = True
                raw = inp.get("emotion", "")
                if raw:
                    result["emotion_value"] = raw
                    if any(kw in raw.lower() for kw in EMOTION_KEYWORDS):
                        result["emotion_found"] = True
    return result
