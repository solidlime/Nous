"""kanban #12: プロジェクトタグがある場合はそのタグを記憶に必ず使用.

- hook 抽出 pipeline: turn.completed detail の project slug → 全保存経路に project:<slug> を強制付与
- MCP memory_create tool: project 引数 → tags に project:<slug> を強制付与
- 既存 project:* タグは尊重（二重付与しない / 状態遷移時に温存する）
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.config.settings import LLMConfig, PluginConfig, Settings
from nous.domain.shared.result import Success

pytestmark = pytest.mark.unit


def _settings() -> Settings:
    s = Settings(
        plugin=PluginConfig(enabled=True, api_key="secr3t"),
        memory_enrichment=LLMConfig(api_key="test-key", model="test-model"),
    )
    s.cors.allowed_origins = ["*"]
    return s


def _mock_ctx(settings: Settings) -> MagicMock:
    from nous.domain.memory.entities import Memory

    ctx = MagicMock()
    ctx.settings = settings
    ctx.persona = "herta"
    ctx.persona_service.get_context.return_value = MagicMock(is_ok=False)
    ctx.memory_service.get_by_tags.return_value = MagicMock(is_ok=False)
    ctx.equipment_service.get_equipment.return_value = MagicMock(is_ok=False)
    ctx.equipment_service.search_items.return_value = MagicMock(is_ok=False)
    ctx.search_engine.search = AsyncMock(return_value=Success([]))
    ctx.vector_store = None
    now = datetime.now()
    ctx.memory_service.create_memory = AsyncMock(
        return_value=Success(Memory(key="mem_p1", content="x", created_at=now, updated_at=now))
    )
    return ctx


def _turn_event_with_project(project: str | None) -> dict:
    detail = {"user_text": "関連記憶注入の苦労", "assistant_text": "覚えておく", "tool_calls_log": []}
    if project is not None:
        detail["project"] = project
    return {
        "type": "turn.completed",
        "summary": "turn: プロジェクトタグ",
        "detail": detail,
    }


def _event_without_project() -> dict:
    return _turn_event_with_project(None)


class TestHookProjectTagForced:
    async def test_project_tag_added_to_fact(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "マダムは紅茶が好き", "importance": 0.7, "tags": ["preference"]}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("nous"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["project:nous", "preference"]

    async def test_project_tag_added_when_llm_omits_tags(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "マダムは紅茶が好き", "importance": 0.7}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("nous"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["project:nous", "auto_extract"]

    async def test_existing_project_tag_not_duplicated(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "既存タグあり", "importance": 0.5, "tags": ["project:kanban"]}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("nous"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["project:kanban"]

    async def test_invalid_project_slug_ignored(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "スラッシュ付き", "importance": 0.5, "tags": ["note"]}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("nous/evil"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["note"]

    async def test_mixed_case_project_slug_normalized(self):
        """AGENTS.md 由来 My_App → my-app 正規化。write_service に拒否されない。"""
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "大文字混在", "importance": 0.5, "tags": ["note"]}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("My_App"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["project:my-app", "note"]

    async def test_no_project_in_detail_means_no_tag(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [{"content": "プロジェクト無しは残す", "importance": 0.5, "tags": ["note"]}],
            "goals": [],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _event_without_project(), "sess_p0")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["note"]

    async def test_goal_create_gets_project_tag(self):
        from nous.application.hooks.memory_extraction import run_hook_extraction

        ctx = _mock_ctx(_settings())
        result = {
            "facts": [],
            "goals": [{"action": "create", "content": "goal1"}],
            "promises": [],
            "context_update": {},
        }
        with patch(
            "nous.application.hooks.memory_extraction.MemoryLLM.process",
            new=AsyncMock(return_value=result),
        ):
            await run_hook_extraction(ctx, "herta", _turn_event_with_project("nous"), "sess_p1")
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["project:nous", "goal", "active"]

    async def test_set_tags_preserves_existing_project_tag(self):
        from nous.application.hooks.memory_extraction import _set_tags

        ctx = _mock_ctx(_settings())
        existing = MagicMock(tags=["project:nous", "goal", "active"])
        ctx.memory_service.get_memory.return_value = Success(existing)
        ctx.memory_service.update_memory.return_value = Success(True)
        assert _set_tags(ctx, "mem_p1", ["goal", "achieved"])
        tags = ctx.memory_service.update_memory.call_args.kwargs["tags"]
        assert "project:nous" in tags


class TestMcpCreateProjectTag:
    @pytest.mark.asyncio
    async def test_create_with_project_param(self, mock_app_context):
        from nous.api.mcp import _tools_memory as m
        from nous.domain.memory.entities import Memory

        mock_app_context.persona_service.get_state_snapshot.return_value = (None, None, None, None)
        now = datetime.now()
        mock_app_context.memory_service.create_memory.return_value = Success(
            Memory(key="mem_mc1", content="x", created_at=now, updated_at=now)
        )
        result = await m._tool_memory_create(mock_app_context, "p", content="hello", project="nous")
        assert '"ok": true' in result
        kwargs = mock_app_context.memory_service.create_memory.call_args.kwargs
        assert kwargs["tags"] == ["project:nous"]

    @pytest.mark.asyncio
    async def test_create_with_project_keeps_existing_project_tag(self, mock_app_context):
        from nous.api.mcp import _tools_memory as m
        from nous.domain.memory.entities import Memory

        mock_app_context.persona_service.get_state_snapshot.return_value = (None, None, None, None)
        now = datetime.now()
        mock_app_context.memory_service.create_memory.return_value = Success(
            Memory(key="mem_mc2", content="x", created_at=now, updated_at=now)
        )
        result = await m._tool_memory_create(
            mock_app_context, "p", content="hello", tags=["project:other"], project="nous"
        )
        assert '"ok": true' in result
        kwargs = mock_app_context.memory_service.create_memory.call_args.kwargs
        assert kwargs["tags"] == ["project:other"]

    @pytest.mark.asyncio
    async def test_create_without_project_no_tag(self, mock_app_context):
        from nous.api.mcp import _tools_memory as m
        from nous.domain.memory.entities import Memory

        mock_app_context.persona_service.get_state_snapshot.return_value = (None, None, None, None)
        now = datetime.now()
        mock_app_context.memory_service.create_memory.return_value = Success(
            Memory(key="mem_mc3", content="x", created_at=now, updated_at=now)
        )
        result = await m._tool_memory_create(mock_app_context, "p", content="hello")
        assert '"ok": true' in result
        kwargs = mock_app_context.memory_service.create_memory.call_args.kwargs
        assert kwargs["tags"] is None

    @pytest.mark.asyncio
    async def test_create_invalid_slug_passed_through_untouched(self, mock_app_context):
        """不正 slug はタグ付与せず tags をそのまま通す（write_service の規約と合致）。"""
        from nous.api.mcp import _tools_memory as m
        from nous.domain.memory.entities import Memory

        mock_app_context.persona_service.get_state_snapshot.return_value = (None, None, None, None)
        now = datetime.now()
        mock_app_context.memory_service.create_memory.return_value = Success(
            Memory(key="mem_mc4", content="x", created_at=now, updated_at=now)
        )
        result = await m._tool_memory_create(mock_app_context, "p", content="hello", tags=["note"], project="nous/evil")
        assert '"ok": true' in result
        kwargs = mock_app_context.memory_service.create_memory.call_args.kwargs
        assert kwargs["tags"] == ["note"]

    @pytest.mark.asyncio
    async def test_create_mixed_case_slug_normalized(self, mock_app_context):
        """MCP 経路も AGENTS.md 由来 My_App を my-app に正規化。"""
        from nous.api.mcp import _tools_memory as m
        from nous.domain.memory.entities import Memory

        mock_app_context.persona_service.get_state_snapshot.return_value = (None, None, None, None)
        now = datetime.now()
        mock_app_context.memory_service.create_memory.return_value = Success(
            Memory(key="mem_mc5", content="x", created_at=now, updated_at=now)
        )
        result = await m._tool_memory_create(mock_app_context, "p", content="hello", project="My_App")
        assert '"ok": true' in result
        kwargs = mock_app_context.memory_service.create_memory.call_args.kwargs
        assert kwargs["tags"] == ["project:my-app"]
