"""チャット実行時のガード: ツール timeout / 永続化の差分検出 / usage / 部分保存。

kanban #52, #53, #56, #60 の回帰テスト。
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

from nous.application.chat.session_store import TreeSessionWindow
from nous.application.chat.tools.registry import ToolRegistry
from nous.infrastructure.llm.base import ToolDefinition


def _tool(name: str = "slow") -> ToolDefinition:
    return ToolDefinition(name=name, description="d", input_schema={"type": "object", "properties": {}})


class _CountingConn:
    """sqlite 接続の薄いラッパ。write 回数を数える（差分検出の検証用）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.writes = 0

    def execute(self, sql: str, params: object = ()) -> sqlite3.Cursor:
        self.writes += 1
        return self._conn.execute(sql, params)  # type: ignore[arg-type]  # pi-lens-ignore: python-sql-injection


def _window() -> tuple[TreeSessionWindow, _CountingConn]:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chat_sessions (persona TEXT, session_id TEXT, messages TEXT,"
        " timestamps TEXT, updated_at TEXT, PRIMARY KEY (persona, session_id))"
    )
    counter = _CountingConn(conn)
    win = TreeSessionWindow()
    win.attach_db(cast("Any", counter), "persona", "session")
    return win, counter


class TestToolTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_result_and_turn_survives(self):
        registry = ToolRegistry(builtin_tools=[_tool()])
        config = cast("Any", SimpleNamespace(tool_result_max_chars=0, tool_timeout_seconds=0.05))
        ctx = cast("Any", SimpleNamespace(persona="p", event_bus=None))

        async def _hang(*args: object, **kwargs: object) -> dict:
            await asyncio.sleep(5)
            return {"ok": True}

        with patch("nous.application.chat.tools.registry.execute_tool", _hang):
            out = await registry.execute(ctx, config, "slow", {})  # pi-lens-ignore: python-sql-injection

        # 例外を投げず、ターンを続行させるためのエラー結果
        assert out["status"] == "error"
        assert "タイムアウト" in out["message"]


class TestPersistDedup:
    def test_unchanged_payload_is_not_rewritten(self):
        win, counter = _window()
        win.add("user", "hi")
        win.flush()
        writes_after_first = counter.writes

        win.flush()  # 内容が変わっていない
        assert counter.writes == writes_after_first

        win.add("assistant", "hello")
        win.flush()
        assert counter.writes > writes_after_first


class TestUsagePersistence:
    def test_usage_is_stored_on_assistant_node(self):
        win, _ = _window()
        msg_id = win.add("assistant", "ok", usage={"input_tokens": 3, "output_tokens": 7})
        win.flush()

        node = win.get_message_by_id(msg_id)
        assert node is not None
        assert node["usage"] == {"input_tokens": 3, "output_tokens": 7}

    def test_usage_survives_reload(self):
        win, counter = _window()
        win.add("assistant", "ok", usage={"total_tokens": 11})
        win.flush()

        reloaded = TreeSessionWindow.from_db(cast("Any", counter), "persona", "session")
        assert reloaded is not None
        messages = reloaded.get_active_path()
        assert messages[-1]["usage"] == {"total_tokens": 11}


class TestPartialPersist:
    def test_partial_text_is_saved_when_turn_crashes(self):
        from nous.application.chat.service import _persist_partial

        added: list[tuple] = []
        session = SimpleNamespace(
            add=lambda role, content, ts, **kw: added.append((role, content, kw)) or "m1",
            flush=lambda: added.append(("flush",)),
        )
        turn_ctx = SimpleNamespace(
            assistant_msg_id=None,
            tool_calls_log=[],
            segments=[{"type": "text", "content": "途中まで"}],
            full_response="",
            usage={"total_tokens": 5},
        )

        _persist_partial(cast("Any", session), cast("Any", turn_ctx), "途中まで")

        assert added[0][0] == "assistant"
        assert added[0][1] == "途中まで"
        assert added[0][2]["usage"] == {"total_tokens": 5}
        assert turn_ctx.assistant_msg_id == "m1"
        assert added[-1] == ("flush",)

    def test_already_saved_turn_is_not_duplicated(self):
        from nous.application.chat.service import _persist_partial

        calls: list[str] = []
        session = SimpleNamespace(add=lambda *a, **k: calls.append("add"), flush=lambda: calls.append("flush"))
        turn_ctx = SimpleNamespace(
            assistant_msg_id="already",
            tool_calls_log=[],
            segments=[],
            full_response="",
            usage=None,
        )

        _persist_partial(cast("Any", session), cast("Any", turn_ctx), "本文")
        assert calls == []
