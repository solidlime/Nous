"""Tests for the session.stopped ingest hook (Phase A: R1/R2 終了フック).

検証要件:
- V1: session.stopped 受信 → ウィンドウ内メッセージが要約され memory_create(tags=["session_summary"]) される
- V2: evict 未発生の短いセッションでも生成される（ウィンドウが空でなければ常に要約される）
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from nous.config.settings import PluginConfig, Settings
from nous.main import MemoryFastMCP

pytestmark = pytest.mark.unit


def _make_app(settings: Settings) -> TestClient:
    """Build an app with events routes; get_settings は settings に差し替え."""
    from nous.api.http.routers.events import register_events_routes

    mcp = MemoryFastMCP(
        "test",
        host="127.0.0.1",
        port=0,
        stateless_http=True,
        json_response=True,
    )
    register_events_routes(mcp)

    import nous.main as main_mod

    original = main_mod.get_settings
    main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
    try:
        return TestClient(mcp.streamable_http_app())
    finally:
        main_mod.get_settings = original


def _mock_ctx(settings: Settings) -> MagicMock:
    """Mock AppContext（auth 判定と DB アクセス用）。"""
    ctx = MagicMock()
    ctx.settings = settings
    ctx.connection.get_memory_db.return_value = MagicMock()
    ctx.event_bus = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# _summarize_session_end（コアロジック）
# ---------------------------------------------------------------------------


async def _add_messages(db, persona: str, session_id: str, *contents: str):
    from nous.application.chat.service import _session_manager

    window = _session_manager.get_or_create(persona, session_id, db=db)
    for i, content in enumerate(contents):
        window.add("user" if i % 2 == 0 else "assistant", content)


class TestSummarizeSessionEnd:
    async def test_summarizes_window_messages(self, sqlite_conn):
        """V1: ウィンドウ内メッセージが summarize_and_store に渡される。"""
        from nous.api.http.routers.events import _summarize_session_end

        db = sqlite_conn.get_memory_db()
        await _add_messages(db, "herta", "sess_sum_1", "hello", "hi there")

        ctx = MagicMock()
        ctx.connection.get_memory_db.return_value = db

        with (
            patch("nous.domain.chat_config.ChatConfigFileRepository") as mock_repo_cls,
            patch(
                "nous.application.chat.summarizer.summarize_and_store",
                new=AsyncMock(return_value=None),
            ) as mock_sum,
        ):
            mock_repo_cls.return_value.get.return_value = MagicMock()

            await _summarize_session_end(ctx, "herta", "sess_sum_1")

        assert mock_sum.await_count == 1
        turns = mock_sum.await_args.args[2]
        assert turns == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    async def test_empty_window_skips(self, sqlite_conn):
        """空ウィンドウはスキップ（Phase A 最小実装）。"""
        from nous.api.http.routers.events import _summarize_session_end

        db = sqlite_conn.get_memory_db()
        ctx = MagicMock()
        ctx.connection.get_memory_db.return_value = db

        with (
            patch("nous.domain.chat_config.ChatConfigFileRepository"),
            patch(
                "nous.application.chat.summarizer.summarize_and_store",
                new=AsyncMock(),
            ) as mock_sum,
        ):
            await _summarize_session_end(ctx, "herta", "sess_sum_empty")

        assert mock_sum.await_count == 0

    async def test_config_load_failure_is_suppressed(self, sqlite_conn):
        """config 取得失敗は非致命（suppress）でスキップ。"""
        from nous.api.http.routers.events import _summarize_session_end

        db = sqlite_conn.get_memory_db()
        await _add_messages(db, "herta", "sess_sum_3", "hello")

        ctx = MagicMock()
        ctx.connection.get_memory_db.return_value = db

        with (
            patch(
                "nous.domain.chat_config.ChatConfigFileRepository",
                side_effect=RuntimeError("no config dir"),
            ),
            patch(
                "nous.application.chat.summarizer.summarize_and_store",
                new=AsyncMock(),
            ) as mock_sum,
        ):
            await _summarize_session_end(ctx, "herta", "sess_sum_3")

        assert mock_sum.await_count == 0


# ---------------------------------------------------------------------------
# ingest 配線（session.stopped 検出 → タスク起動）
# ---------------------------------------------------------------------------


class TestIngestSessionStopHook:
    SETTINGS = Settings(plugin=PluginConfig(enabled=True, api_key="secr3t"))

    def _post(self, body: dict) -> tuple[object, AsyncMock]:
        client = _make_app(self.SETTINGS)
        with (
            patch(
                "nous.api.http.routers.events._safe_get_context",
                return_value=_mock_ctx(self.SETTINGS),
            ),
            patch(
                "nous.api.http.routers.events._summarize_session_end",
                new=AsyncMock(),
            ) as mock_hook,
            client,
        ):
            resp = client.post(
                "/api/events/ingest",
                json=body,
                headers={"Authorization": "Bearer secr3t"},
            )
            # fire-and-forget タスクをアプリのループで処理させる
            client.portal.call(asyncio.sleep, 0.05)
        return resp, mock_hook

    def test_session_stopped_triggers_hook(self):
        """V1: session.stopped を含むイベント群 → サマリタスクが起動する。"""
        body = {
            "session_id": "sess_stop_1",
            "persona": "herta",
            "events": [
                {"type": "session.stopped", "summary": "session ended"},
                {"type": "tool_call", "summary": "some tool"},
            ],
        }
        resp, mock_hook = self._post(body)
        assert resp.status_code == 200
        assert mock_hook.await_count == 1

    def test_without_session_stopped_skips(self):
        """session.stopped を含まない → タスクは起動しない。"""
        body = {
            "session_id": "sess_stop_2",
            "persona": "herta",
            "events": [{"type": "tool_call", "summary": "some tool"}],
        }
        resp, mock_hook = self._post(body)
        assert resp.status_code == 200
        assert mock_hook.await_count == 0
