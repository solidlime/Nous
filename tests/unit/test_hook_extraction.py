"""Tests for Task B: pi hook extraction pipeline（turn.completed → 記憶化）.

検証要件（計画書 §4）:
- facts 1 件 → memory_service.create_memory が呼ばれる
- LLM が空 result → 例外が外に漏れず、記憶を作らない
- 既存記憶と類似（≥0.85）なら skip
- events 列に turn.completed が無ければ何も呼ばれない
- 認証 fail（plugin off / API key 不一致）では抽出しない
- LLM 失敗は session_events に hook_extraction.failed を1行残す（no-op）
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from nous.config.settings import LLMConfig, PluginConfig, Settings
from nous.domain.shared.result import Success
from nous.main import MemoryFastMCP

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(plugin: PluginConfig | None = None) -> Settings:
    s = Settings(
        plugin=plugin or PluginConfig(enabled=True, api_key="secr3t"),
        memory_enrichment=LLMConfig(api_key="test-key", model="test-model"),
    )
    s.cors.allowed_origins = ["*"]
    return s


def _mock_ctx(settings: Settings, *, duplicate_score: float = 0.0) -> MagicMock:
    """MemoryLLM 呼び出しと保存だけを検証できる最小の AppContext mock。"""
    from datetime import datetime

    from nous.domain.memory.entities import Memory

    ctx = MagicMock()
    ctx.settings = settings
    ctx.persona = "herta"

    # _build_memory_llm_context が触るサービスは「空」を返す
    ctx.persona_service.get_context.return_value = MagicMock(is_ok=False)
    ctx.memory_service.get_by_tags.return_value = MagicMock(is_ok=False)
    ctx.equipment_service.get_equipment.return_value = MagicMock(is_ok=False)
    ctx.equipment_service.search_items.return_value = MagicMock(is_ok=False)

    hit = MagicMock(score=duplicate_score)
    ctx.search_engine.search = AsyncMock(return_value=Success([hit] if duplicate_score else []))
    ctx.vector_store = None
    now = datetime.now()
    ctx.memory_service.create_memory = AsyncMock(
        return_value=Success(Memory(key="mem_hook_1", content="x", created_at=now, updated_at=now))
    )
    return ctx


def _turn_event(user: str = "紅茶が好き", assistant: str = "覚えておく") -> dict:
    return {
        "type": "turn.completed",
        "summary": "turn: 紅茶",
        "detail": {"user_text": user, "assistant_text": assistant, "tool_calls_log": []},
    }


def _llm_result(**overrides) -> dict:
    base = {"facts": [], "goals": [], "promises": [], "context_update": {}}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# run_hook_extraction（コアロジック）
# ---------------------------------------------------------------------------


class TestRunHookExtraction:
    async def test_saves_extracted_fact(self):
        """facts 1 件 → create_memory(content=..., importance=..., tags=...) が呼ばれる。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = _llm_result(facts=[{"content": "マダムは紅茶が好き", "importance": 0.7, "tags": ["preference"]}])

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ) as mock_process:
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_hook_1")

        assert mock_process.await_count == 1
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["content"] == "マダムは紅茶が好き"
        assert kwargs["importance"] == pytest.approx(0.7)
        assert kwargs["tags"] == ["preference"]

    async def test_empty_result_is_noop(self):
        """LLM が空 result → 例外を出さず、記憶も作らない。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value={}),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_hook_2")

        assert ctx.memory_service.create_memory.await_count == 0

    async def test_llm_exception_is_suppressed_and_recorded(self, sqlite_conn):
        """LLM 例外 → 例外を外に漏らさず、session_events に hook_extraction.failed を残す。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        ctx.connection = sqlite_conn

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_hook_3")

        assert ctx.memory_service.create_memory.await_count == 0
        rows = (
            sqlite_conn.get_memory_db()
            .execute("SELECT event_type, summary FROM session_events WHERE session_id = ?", ("sess_hook_3",))
            .fetchall()
        )
        assert rows and rows[0][0] == "hook_extraction.failed"

    async def test_duplicate_fact_skipped(self):
        """類似 ≥0.85 の既存記憶があれば create_memory を呼ばない。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings(), duplicate_score=0.9)
        result = _llm_result(facts=[{"content": "マダムは紅茶が好き", "importance": 0.7}])

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_hook_4")

        assert ctx.memory_service.create_memory.await_count == 0

    async def test_empty_turn_text_skips_llm(self):
        """user/assistant が両方空なら LLM を呼ばない（turn 消費の無駄撃ち防止）。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=_llm_result()),
        ) as mock_process:
            await run_hook_extraction(ctx, "herta", _turn_event(user="", assistant=""), "sess_hook_5")

        assert mock_process.await_count == 0


# ---------------------------------------------------------------------------
# ingest 配線（turn.completed 検出 → fire-and-forget）
# ---------------------------------------------------------------------------


def _make_client(settings: Settings) -> TestClient:
    from nous.api.http.routers.chat.events import register_events_routes

    mcp = MemoryFastMCP("test")
    register_events_routes(mcp)

    import nous.main as main_mod

    original = main_mod.get_settings
    main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
    try:
        return TestClient(mcp.streamable_http_app())
    finally:
        main_mod.get_settings = original


class TestIngestTurnCompletedHook:
    def _post(self, body: dict, *, settings: Settings | None = None, headers: dict | None = None):
        settings = settings or _settings()
        client = _make_client(settings)
        ctx = _mock_ctx(settings)
        with (
            patch("nous.api.http.routers.chat.events._safe_get_context", return_value=ctx),
            patch(
                "nous.application.hooks.memory_extraction.run_hook_extraction",
                new=AsyncMock(),
            ) as mock_hook,
            client,
        ):
            resp = client.post(
                "/api/events/ingest",
                json=body,
                headers=headers or {"Authorization": "Bearer secr3t"},
            )
            client.portal.call(asyncio.sleep, 0.05)
        return resp, mock_hook

    def test_turn_completed_triggers_hook(self):
        """turn.completed を含む → run_hook_extraction が 1 回起動する。"""
        body = {"session_id": "sess_t1", "persona": "herta", "events": [_turn_event()]}
        resp, mock_hook = self._post(body)
        assert resp.status_code == 200
        assert mock_hook.await_count == 1
        assert mock_hook.await_args.args[1] == "herta"

    def test_without_turn_completed_skips(self):
        """turn.completed も session.stopped も無い → 何も起動しない。"""
        body = {
            "session_id": "sess_t2",
            "persona": "herta",
            "events": [{"type": "tool_call", "summary": "some tool"}],
        }
        resp, mock_hook = self._post(body)
        assert resp.status_code == 200
        assert mock_hook.await_count == 0

    def test_session_stopped_does_not_run_hook(self):
        """session.stopped は既存 _summarize_session_end 専用（二重保存防止）。"""
        body = {
            "session_id": "sess_t3",
            "persona": "herta",
            "events": [{"type": "session.stopped", "summary": "session ended"}],
        }
        with patch(
            "nous.api.http.routers.chat.events._summarize_session_end",
            new=AsyncMock(),
        ) as mock_summary:
            resp, mock_hook = self._post(body)
        assert resp.status_code == 200
        assert mock_summary.await_count == 1
        assert mock_hook.await_count == 0

    def test_disabled_plugin_does_not_run_hook(self):
        """plugin off（403）→ 抽出は走らない。"""
        settings = _settings(PluginConfig(enabled=False))
        body = {"session_id": "sess_t4", "persona": "herta", "events": [_turn_event()]}
        resp, mock_hook = self._post(body, settings=settings, headers={})
        assert resp.status_code == 403
        assert mock_hook.await_count == 0

    def test_wrong_api_key_does_not_run_hook(self):
        """API key 不一致（401）→ 抽出は走らない。"""
        body = {"session_id": "sess_t5", "persona": "herta", "events": [_turn_event()]}
        resp, mock_hook = self._post(body, headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
        assert mock_hook.await_count == 0


# ---------------------------------------------------------------------------
# context_update: relationship_status
# ---------------------------------------------------------------------------


class TestRelationshipStatusApply:
    async def test_relationship_status_is_persisted(self):
        """context_update.relationship_status → update_relationship に渡る。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = _llm_result(context_update={"relationship_status": "信頼している友人"})

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_rel_1")

        ctx.persona_service.update_relationship.assert_called_once_with("herta", "信頼している友人")

    async def test_update_context_tool_call_skips_relationship_status(self):
        """Web 経路（input 付き）: メインLLMが書いたターンは抽出側の関係性を適用しない。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = _llm_result(context_update={"relationship_status": "他人"})
        event = _turn_event()
        event["detail"]["tool_calls_log"] = [
            {"name": "update_context", "input": {"relationship_status": "信頼している友人"}}
        ]

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", event, "sess_rel_2")

        ctx.persona_service.update_relationship.assert_not_called()

    async def test_pi_tool_log_shape_skips_relationship_status(self):
        """pi 経路: 本物の nous-events.ts が積む shape（name/input 無し、arg_keys のみ）でも skip する。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = _llm_result(context_update={"relationship_status": "他人"})
        event = _turn_event()
        event["detail"]["tool_calls_log"] = [
            {
                "tool": "mcp__nous__update_context",
                "args_summary": "",
                "arg_keys": ["relationship_status"],
                "ok": True,
                "ms": 10,
            }
        ]

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", event, "sess_rel_pi_1")

        ctx.persona_service.update_relationship.assert_not_called()

    async def test_pi_item_tool_name_skips_inventory(self):
        """pi の MCP 名（mcp__nous__item_add）でも inventory 上書きを skip する。"""
        from nous.application.chat.memory_extractor import _context_update_skips, item_tools_used

        log = [{"tool": "mcp__nous__item_add", "args_summary": "x", "arg_keys": ["name"], "ok": True, "ms": 3}]
        assert _context_update_skips(log)[4] is True
        assert item_tools_used(log) is True

    async def test_blank_relationship_status_is_not_applied(self):
        """空文字は update_relationship が Failure を返すので呼ばない。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = _llm_result(context_update={"relationship_status": "   "})

        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event(), "sess_rel_3")

        ctx.persona_service.update_relationship.assert_not_called()
