"""Tests for context-related MCP tool handlers (update_context, get_context)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.persona.entities import PersonaState
from nous.domain.search.engine import SearchResult
from nous.domain.shared.errors import DomainError
from nous.domain.shared.result import Failure, Success

UTC = UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(key: str = "mem_001", content: str = "test content") -> Memory:
    now = datetime.now(UTC)
    return Memory(key=key, content=content, created_at=now, updated_at=now)


def _search_result(key: str = "mem_001", score: float = 0.8) -> SearchResult:
    return SearchResult(memory=_mem(key), score=score, source="keyword")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app_context():
    ctx = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.search_engine = MagicMock()
    ctx.persona_service = MagicMock()
    ctx.entity_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.vector_store = None  # no Qdrant by default
    ctx.settings = MagicMock()
    ctx.settings.contradiction_threshold = 0.85
    return ctx


@pytest.fixture
def registered_tools(mock_app_context):
    """
    Call register_tools with a mock FastMCP, capturing the tool functions
    by intercepting the @mcp.tool() decorator calls.
    """
    tools: dict[str, object] = {}

    def mock_tool_decorator():
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = mock_tool_decorator

    with (
        patch("nous.api.mcp.tools.AppContextRegistry") as mock_registry_cls,
        patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
    ):
        mock_registry_cls.get.return_value = mock_app_context

        from nous.api.mcp.tools import register_tools

        register_tools(mock_mcp)

        # Yield both the tools dict and the patched context so tests can
        # configure return values.
        yield tools, mock_app_context, mock_registry_cls


# ---------------------------------------------------------------------------
# update_context()
# ---------------------------------------------------------------------------


class TestUpdateContext:
    @pytest.fixture(autouse=True)
    def _mock_expression(self):
        """update_context の表情同期を inert 化（各テストで検証できるよう mock を差し出す）。"""
        with patch(
            "nous.application.chat.pipeline.post.update_expression",
            new_callable=AsyncMock,
        ) as m:
            yield m

    @pytest.mark.asyncio
    async def test_update_emotion(self, registered_tools, _mock_expression):
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_emotion.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(emotion="joy", emotion_intensity=0.9)
        assert "emotion=joy" in result
        ctx.persona_service.update_emotion.assert_called_once_with("test_persona", "joy", 0.9, context="manual_update")
        _mock_expression.assert_awaited_once_with(ctx, ctx.config, "joy")

    @pytest.mark.asyncio
    async def test_update_emotion_expression_failure_is_swallowed(self, registered_tools, _mock_expression):
        """表情同期が失敗しても context 更新自体は成功する。"""
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_emotion.return_value = Success(None)
        _mock_expression.side_effect = RuntimeError("boom")
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(emotion="sad")
        assert "emotion=sad" in result

    @pytest.mark.asyncio
    async def test_update_physical_state(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_physical_state.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(physical_state="tired", mental_state="focused")
        assert "physical_state" in result
        assert "mental_state" in result

    @pytest.mark.asyncio
    async def test_update_no_changes(self, registered_tools):
        tools, ctx, _ = registered_tools
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context()
        assert "No changes" in result
        ctx.persona_service.record_conversation_time.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_records_conversation_time(self, registered_tools):
        """自発的更新（context_note/relationship 等）は最終接触時刻を記録する。"""
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_relationship.return_value = Success(None)
        ctx.persona_service.update_persona_info.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(relationship_status="friends", context_note="会話中")
        assert "relationship=friends" in result
        ctx.persona_service.record_conversation_time.assert_called_once_with("test_persona")

    @pytest.mark.asyncio
    async def test_update_relationship_status(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_relationship.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(relationship_status="friends")
        assert "relationship=friends" in result

    @pytest.mark.asyncio
    async def test_update_nickname_shortcut(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_persona_info.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(nickname="Taro")
        assert "nickname=Taro" in result

    @pytest.mark.asyncio
    async def test_update_user_info(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.update_user_info.return_value = Success(None)
        update_context = tools["update_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await update_context(user_info={"name": "Alice", "nickname": "Ali"})
        assert "user_info updated" in result


# ---------------------------------------------------------------------------
# get_context()
# ---------------------------------------------------------------------------


class TestGetContext:
    @pytest.mark.asyncio
    async def test_get_context_success(self, registered_tools):
        tools, ctx, _ = registered_tools
        state = PersonaState(persona="test_persona", emotion="joy", emotion_intensity=0.8)
        ctx.persona_service.get_context.return_value = Success(state)
        ctx.memory_service.get_stats.return_value = Success({"total": 10})
        ctx.memory_service.list_blocks.return_value = Success([])
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.memory_service.get_recent_searches.return_value = Success([])
        ctx.memory_service.count_decayed_important.return_value = Success(0)
        ctx.memory_service.get_memory_index.return_value = Success(None)
        ctx.persona_service.record_conversation_time.return_value = Success(None)
        get_context = tools["get_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await get_context()
        assert "test_persona" in result
        assert "CURRENT STATE" in result
        assert "joy" in result

    @pytest.mark.asyncio
    async def test_get_context_persona_service_failure(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_context.return_value = Failure(DomainError("persona error"))
        get_context = tools["get_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await get_context()
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_context_shows_active_goals(self, registered_tools):
        tools, ctx, _ = registered_tools
        state = PersonaState(persona="test_persona")
        goal_mem = _mem("goal_001", "Finish project")
        goal_mem.tags = ["goal", "active"]
        ctx.persona_service.get_context.return_value = Success(state)
        ctx.memory_service.get_stats.return_value = Success({})
        ctx.memory_service.list_blocks.return_value = Success([])
        ctx.memory_service.get_by_tags.side_effect = lambda tags: Success([goal_mem]) if "goal" in tags else Success([])
        ctx.memory_service.get_recent_searches.return_value = Success([])
        ctx.memory_service.count_decayed_important.return_value = Success(0)
        ctx.memory_service.get_memory_index.return_value = Success(None)
        ctx.persona_service.record_conversation_time.return_value = Success(None)
        get_context = tools["get_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await get_context()
        assert "Finish project" in result

    # ------------------------------------------------------------------
    # Emotion decay notification
    # ------------------------------------------------------------------

    def test_format_emotion_decay_note_emotion_change(self):
        """_format_emotion_decay_note uses natural language for emotion→neutral."""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        result = EmotionDecayResult(
            before_emotion="anger",
            before_intensity=0.72,
            after_emotion="neutral",
            after_intensity=0.0,
            elapsed_hours=48.0,
        )
        note = _format_emotion_decay_note(result)
        assert "anger" in note
        assert "消失した" in note
        assert "2日" in note
        assert "(" not in note  # no debug format like (0.72)

    def test_format_emotion_decay_note_same_emotion(self):
        """_format_emotion_decay_note uses natural language for same emotion decay."""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        result = EmotionDecayResult(
            before_emotion="joy",
            before_intensity=0.9,
            after_emotion="joy",
            after_intensity=0.3,
            elapsed_hours=24.0,
        )
        note = _format_emotion_decay_note(result)
        assert "joy" in note
        assert "減衰した" in note
        assert "1日" in note
        assert "(" not in note  # no debug format

    def test_format_emotion_decay_note_none(self):
        """_format_emotion_decay_note returns empty string for None."""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note

        assert _format_emotion_decay_note(None) == ""

    def test_format_emotion_decay_note_minutes(self):
        """_format_emotion_decay_note shows minutes when < 1h."""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        result = EmotionDecayResult(
            before_emotion="joy",
            before_intensity=0.8,
            after_emotion="neutral",
            after_intensity=0.0,
            elapsed_hours=0.5,
        )
        note = _format_emotion_decay_note(result)
        assert "30分" in note
        assert "消失した" in note

    @pytest.mark.asyncio
    async def test_get_context_includes_decay_notification(self, registered_tools):
        """When emotion decay is applied, context output includes the before→after line."""
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        tools, ctx, _ = registered_tools
        state_before = PersonaState(
            persona="test_persona",
            emotion="anger",
            emotion_intensity=0.72,
            last_conversation_time=datetime.now(UTC) - timedelta(hours=48),
        )
        state_after = PersonaState(
            persona="test_persona",
            emotion="neutral",
            emotion_intensity=0.0,
            last_conversation_time=datetime.now(UTC) - timedelta(hours=48),
        )
        # First get_context returns before-decay state, second returns after
        ctx.persona_service.get_context.side_effect = [Success(state_before), Success(state_after)]
        ctx.persona_service.update_emotion.return_value = Success(None)
        ctx.memory_service.get_stats.return_value = Success({"total": 10})
        ctx.memory_service.list_blocks.return_value = Success([])
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.memory_service.get_recent_searches.return_value = Success([])
        ctx.memory_service.count_decayed_important.return_value = Success(0)
        ctx.memory_service.get_memory_index.return_value = Success(None)
        ctx.persona_service.record_conversation_time.return_value = Success(None)
        get_context = tools["get_context"]
        decay_result = EmotionDecayResult(
            before_emotion="anger",
            before_intensity=0.72,
            after_emotion="neutral",
            after_intensity=0.0,
            elapsed_hours=48.0,
        )
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
            patch(
                "nous.domain.persona.emotion_decay.apply_emotion_decay_if_needed",
                return_value=decay_result,
            ),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await get_context()
        assert "anger" in result
        assert "消失した" in result
        assert "2日" in result

    @pytest.mark.asyncio
    async def test_get_context_no_decay_no_notification(self, registered_tools):
        """When no decay happens, context output should NOT include a decay line."""
        tools, ctx, _ = registered_tools
        state = PersonaState(
            persona="test_persona",
            emotion="joy",
            emotion_intensity=0.8,
            last_conversation_time=datetime.now(UTC),
        )
        ctx.persona_service.get_context.return_value = Success(state)
        ctx.persona_service.update_emotion.return_value = Success(None)
        ctx.memory_service.get_stats.return_value = Success({"total": 10})
        ctx.memory_service.list_blocks.return_value = Success([])
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.memory_service.get_recent_searches.return_value = Success([])
        ctx.memory_service.count_decayed_important.return_value = Success(0)
        ctx.memory_service.get_memory_index.return_value = Success(None)
        ctx.persona_service.record_conversation_time.return_value = Success(None)
        get_context = tools["get_context"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
            patch(
                "nous.domain.persona.emotion_decay.apply_emotion_decay_if_needed",
                return_value=None,
            ),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await get_context()
        assert "CURRENT STATE" in result
        assert "joy" in result
        assert "faded" not in result.lower()
