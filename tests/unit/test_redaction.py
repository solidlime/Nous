"""kanban #75: 秘密値がログ・イベントに残らないこと。

`tool.called` の `params_summary` は LLM 生成の任意 dict を文字列化したものなので、
URL に埋まったトークン・`export API_KEY=...`・MCP の認証ヘッダがそのまま
`session_events`（永続）と SSE に出ていた。例外文字列も同様。
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from nous.api.mcp._tools_helpers import _emit_tool_called
from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.config.redaction import redact_params, redact_text


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, event_type, data):
        self.events.append((event_type, data))


# ---------------------------------------------------------------------------
# redact_params / redact_text
# ---------------------------------------------------------------------------


def test_params_masks_secret_keys():
    out = redact_params({"api_key": "sk-live-123", "query": "hello"})
    assert "sk-live-123" not in out
    assert "***" in out
    assert "hello" in out


def test_params_masks_token_inside_url_value():
    # fetch_content の URL にトークンが載る形。キー名は url なので辞書側では潰れない。
    out = redact_params({"url": "https://api.example.com/v1?token=abcdef123&q=1"})
    assert "abcdef123" not in out
    assert "q=1" in out


def test_text_masks_bearer_and_env_assignment():
    out = redact_text("curl -H 'Authorization: Bearer eyJhbGciOi.abc' && export API_KEY=sk-999")
    assert "eyJhbGciOi.abc" not in out
    assert "sk-999" not in out


def test_text_truncates_without_cutting_marker():
    out = redact_text("x" * 500, 20)
    assert len(out) == 20
    assert out.endswith("…")


def test_params_non_dict_is_masked():
    out = redact_params("password=hunter2")
    assert "hunter2" not in out


# ---------------------------------------------------------------------------
# tool.called 経由（MCP ツールの共通経路）
# ---------------------------------------------------------------------------


def test_emit_tool_called_masks_params_and_error():
    ctx: Any = SimpleNamespace(event_bus=_Bus(), session_id="s1")
    asyncio.run(
        _emit_tool_called(
            ctx,
            "bash",
            "failed",
            False,
            params_summary=str({"command": "export API_KEY=sk-deadbeef"}),
            error="IntegrityError: UNIQUE constraint failed: session_events.id (key sk-deadbeef)",
        )
    )
    _t, data = ctx.event_bus.events[0]
    assert "sk-deadbeef" not in data["params_summary"]
    assert "sk-deadbeef" not in data["error"]
    assert "UNIQUE constraint" in data["error"]  # 原因は残す


# ---------------------------------------------------------------------------
# 設定保存ログ
# ---------------------------------------------------------------------------


@pytest.fixture
def config_manager():
    RuntimeConfigManager.reset()
    mgr = RuntimeConfigManager()
    yield mgr
    RuntimeConfigManager.reset()


def test_update_logs_masked_value(config_manager, caplog):
    with caplog.at_level(logging.INFO):
        config_manager.update("qdrant", "api_key", "super-secret-key")
    assert "super-secret-key" not in caplog.text
    assert "qdrant.api_key = ***" in caplog.text
