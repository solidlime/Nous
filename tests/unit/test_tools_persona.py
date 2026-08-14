"""Tests for _tools_persona.py — get_context one-shot memory reading."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success


def _make_memory(
    key: str = "mem_001",
    content: str = "test content",
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Memory:
    ts = created_at or datetime(2026, 7, 10, 12, 0)
    return Memory(
        key=key,
        content=content,
        tags=tags or [],
        created_at=ts,
        updated_at=updated_at or ts,
    )


@pytest.fixture
def mock_ctx():
    """Minimal mock AppContext for _tool_get_context."""
    ctx = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.memory_repo = MagicMock()
    ctx.persona_service = MagicMock()
    ctx.search_engine = MagicMock()
    ctx.equipment_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.entity_service = MagicMock()
    ctx.vector_store = None
    ctx.settings = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_get_context_skips_consumed_memories(mock_ctx):
    """consumed 済みメモリは空リストが返る → 注入されない"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])  # consumed = empty
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    # consumed はスキップされるので注入されない
    assert result["ok"] is True
    assert "前回セッションからの状態" not in result["result"]
    assert "口調" not in result["result"]


@pytest.mark.asyncio
async def test_get_context_includes_one_shot_memories(mock_ctx):
    """one-shot メモリが存在する場合は結果に含まれる"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.side_effect = [
        Success([_make_memory("m1", content="physical_state: 元気", tags=["physical_state"])]),
        Success([]),  # mental_state: consumed
    ]
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")
    assert result["ok"] is True
    assert "💪 身体状態" in result["result"]
    assert "元気" in result["result"]
    # mental_state consumed → not shown
    assert "🧠 精神状態" not in result["result"]


@pytest.mark.asyncio
async def test_get_context_both_one_shot_present(mock_ctx):
    """両方の one-shot メモリが存在する場合、両方とも表示される"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.side_effect = [
        Success([_make_memory("m1", content="physical_state: 元気", tags=["physical_state"])]),
        Success([_make_memory("m2", content="mental_state: 集中", tags=["mental_state"])]),
    ]
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")
    assert result["ok"] is True
    assert "💪 身体状態" in result["result"]
    assert "元気" in result["result"]
    assert "🧠 精神状態" in result["result"]
    assert "集中" in result["result"]


@pytest.mark.asyncio
async def test_get_context_dedup_recent_vs_top_memories(mock_ctx):
    """top_memories と recent で同一 key の記憶は recent 側から除外され、重複表示されない"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    shared = _make_memory("shared_key", content="SHARED_MEMORY_CONTENT", tags=["episodic"])
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([shared])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([shared])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    # ESSENTIAL STORY には出るが Recent Memories では除外され、本文に1回だけ現れる
    assert result["ok"] is True
    assert "SHARED_MEMORY_CONTENT" in result["result"]
    assert result["result"].count("SHARED_MEMORY_CONTENT") == 1


@pytest.mark.asyncio
async def test_get_context_summaries_sorted_by_updated_at(mock_ctx):
    """session_summary は updated_at 降順でソートされ、最新のサマリが先に表示される"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    # 古い updated_at だが新しい created_at を持つ記憶（ソートが created_at でないことを検証）
    old = _make_memory(
        "sum_old",
        content="OLD_SUMMARY_TEXT",
        tags=["session_summary"],
        created_at=datetime(2026, 8, 10),
        updated_at=datetime(2026, 7, 1),
    )
    new = _make_memory(
        "sum_new",
        content="NEW_SUMMARY_TEXT",
        tags=["session_summary"],
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 8, 10),
    )
    mock_ctx.persona_service.get_context.return_value = Success(state)

    def get_by_tags_side_effect(tags, include_consumed=False):
        if tags == ["session_summary"]:
            return Success([old, new])  # 並び順は保証されない想定（古い順で返す）
        return Success([])

    mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert "📝 NEW_SUMMARY_TEXT" in result["result"]
    assert "📝 OLD_SUMMARY_TEXT" in result["result"]
    # updated_at が新しい NEW が先に表示される
    assert result["result"].index("NEW_SUMMARY_TEXT") < result["result"].index("OLD_SUMMARY_TEXT")
