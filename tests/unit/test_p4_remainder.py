"""P4 remainder tests — M1 interference / M2 sweep / M3 metamemory / M4 temporal links / L2 task context."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success


def _mem(key: str, content: str = "内容", tags: list[str] | None = None, **kwargs) -> Memory:
    now = datetime(2026, 9, 19, 12, 0)
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.7, tags=tags or [], **kwargs)


# ===========================================================================
# M3 — metamemory
# ===========================================================================


class TestMetamemory:
    @pytest.mark.asyncio
    async def test_empty_search_marks_unknown(self):
        from nous.api.mcp._tools_memory import _tool_memory_search

        ctx = MagicMock()
        ctx.search_engine.search = AsyncMock(return_value=Success([]))
        ctx.memory_service.count_memories.return_value = Success(42)
        ctx.event_bus.publish = AsyncMock()
        out = json.loads(await _tool_memory_search(ctx, "p1", "存在しない話題"))
        assert out["ok"] is True
        assert out["data"]["memories"] == []
        assert out["meta"]["unknown"] is True
        assert out["meta"]["stored_total"] == 42


# ===========================================================================
# M4 — temporal links
# ===========================================================================


class TestTemporalLinkBonus:
    def test_same_day_and_place_bonus(self):
        from nous.domain.memory.link_service import MemoryLinkService

        day = datetime(2026, 9, 19, 10, 0)
        m1 = _mem("a", kind="episodic", episodic_time="2026-09-19T10:00", episodic_place="京都")
        m2 = _mem("b", kind="episodic", episodic_time="2026-09-19T18:00", episodic_place="京都")
        assert day is not None
        assert MemoryLinkService._temporal_bonus(m1, m2) == pytest.approx(0.3)

    def test_different_day_no_bonus(self):
        from nous.domain.memory.link_service import MemoryLinkService

        m1 = _mem("a", kind="episodic", episodic_time="2026-09-18T10:00")
        m2 = _mem("b", kind="episodic", episodic_time="2026-09-19T10:00")
        assert MemoryLinkService._temporal_bonus(m1, m2) == 0.0

    def test_non_episodic_never_gets_bonus(self):
        from nous.domain.memory.link_service import MemoryLinkService

        m1 = _mem("a", kind="semantic", episodic_time="2026-09-19T10:00", episodic_place="京都")
        m2 = _mem("b", kind="semantic", episodic_time="2026-09-19T10:00", episodic_place="京都")
        assert MemoryLinkService._temporal_bonus(m1, m2) == 0.0

    def test_created_at_fallback_for_day(self):
        from nous.domain.memory.link_service import MemoryLinkService

        m1 = _mem("a", kind="episodic")
        m2 = _mem("b", kind="episodic")
        assert MemoryLinkService._temporal_bonus(m1, m2) == pytest.approx(0.15)


# ===========================================================================
# L2 — task context query expansion
# ===========================================================================


class TestTaskContextExpansion:
    def test_terms_from_active_task_state(self):
        from nous.application.chat.pipeline.prepare import _task_context_terms

        ctx = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success(
            [_mem("t1", "v4.0 実装中", tags=["task_state", "project:nous", "task_state"])]
        )
        terms = _task_context_terms(ctx)
        assert "project:nous" in terms
        assert "task_state" not in terms

    def test_no_task_state_yields_empty(self):
        from nous.application.chat.pipeline.prepare import _task_context_terms

        ctx = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success([])
        assert _task_context_terms(ctx) == ""

    def test_query_unchanged_without_terms(self):
        from nous.application.chat.pipeline.prepare import _recall_query_with_task_context

        session = MagicMock()
        session._messages = []
        ctx = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success([])
        assert _recall_query_with_task_context(ctx, session, "こんにちは") == "こんにちは"

    def test_query_extended_with_terms(self):
        from nous.application.chat.pipeline.prepare import _recall_query_with_task_context

        session = MagicMock()
        session._messages = []
        ctx = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success([_mem("t1", tags=["task_state", "project:nous"])])
        assert _recall_query_with_task_context(ctx, session, "進捗どう？").endswith("project:nous")
