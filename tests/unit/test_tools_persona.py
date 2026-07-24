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
) -> Memory:
    ts = created_at or datetime(2026, 7, 10, 12, 0)
    return Memory(
        key=key,
        content=content,
        tags=tags or [],
        created_at=ts,
        updated_at=ts,
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
    mock_ctx.memory_service.get_by_tags.return_value = Success([])  # all empty = consumed
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
