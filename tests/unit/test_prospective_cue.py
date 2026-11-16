"""Prospective-memory cue boundaries — audit M2 (v4.0).

``due_cues`` is shared by get_context (live injection) and ProspectiveWorker
(hourly sweep). These tests pin the window rules both callers depend on:
inside 24h fires, beyond it does not, expired is not restated, and a memory
with no cue is never picked up. Event cues are the other half.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.cue import (
    DUE_WINDOW_HOURS,
    due_cues,
    event_cue_tag,
    event_cued_memories,
    time_cue_tag,
)
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str, content: str = "約束", tags: list[str] | None = None) -> Memory:
    now = datetime(2026, 9, 19, 12, 0)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.8,
        tags=tags or [],
    )


class TestDueWindow:
    def test_deadline_inside_24h_fires(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", "面接", tags=[time_cue_tag(now + timedelta(hours=3))])
        due = due_cues([mem], now, allow_overdue=False)
        assert [m.key for m, _ in due] == ["m1"]
        assert due[0][1] == "in 3h"

    def test_deadline_beyond_24h_does_not_fire(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", tags=[time_cue_tag(now + timedelta(hours=DUE_WINDOW_HOURS + 1))])
        assert due_cues([mem], now, allow_overdue=False) == []

    def test_expired_is_not_injected(self):
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", "古い約束", tags=[time_cue_tag(now - timedelta(hours=2))])
        assert due_cues([mem], now, allow_overdue=False) == []

    def test_expired_within_grace_still_listed_when_allowed(self):
        # 期限切れは別扱い（既定の allow_overdue=True は MCP の goal 行が使う）。
        now = datetime(2026, 9, 19, 12, 0)
        mem = _mem("m1", "古い約束", tags=[time_cue_tag(now - timedelta(hours=2))])
        due = due_cues([mem], now)
        assert len(due) == 1
        assert "overdue" in due[0][1]

    def test_memory_without_cue_is_ignored(self):
        now = datetime(2026, 9, 19, 12, 0)
        assert due_cues([_mem("m1", tags=["goal", "active"])], now, allow_overdue=False) == []


class TestEventMatch:
    def test_entity_in_text_fires(self):
        mem = _mem("m1", "健康診断の結果を聞く", tags=[event_cue_tag("健康診断")])
        assert [m.key for m in event_cued_memories([mem], "明日は健康診断だよ")] == ["m1"]

    def test_unrelated_text_does_not_fire(self):
        mem = _mem("m1", tags=[event_cue_tag("健康診断")])
        assert event_cued_memories([mem], "今日はコードを書いた") == []


def _state() -> MagicMock:
    state = MagicMock()
    state.persona = "p1"
    state.emotion = None
    state.environment = None
    state.relationship_status = None
    state.user_info = {}
    state.persona_info = {}
    return state


def _ctx(goals: list[Memory]) -> MagicMock:
    ctx = MagicMock()
    ctx.memory_service.get_by_tags.return_value = Success(goals)
    ctx.memory_service.get_top_by_importance.return_value = Success([])
    ctx.persona_service.get_emotion_history.return_value = Success([])
    ctx.equipment_service.get_equipment.return_value = Success({})
    return ctx


class TestContextInjection:
    @pytest.mark.asyncio
    async def test_due_goal_injected_and_expired_skipped(self):
        from nous.application.chat.pipeline.prepare import _build_context_section

        now = get_now()
        due = _mem("m1", "面接の約束", tags=["goal", "active", time_cue_tag(now + timedelta(hours=2))])
        expired = _mem("m2", "期限切れの約束", tags=["goal", "active", time_cue_tag(now - timedelta(hours=2))])
        turn_ctx = MagicMock()
        turn_ctx.user_message = ""
        text = await _build_context_section(_ctx([due, expired]), _state(), turn_ctx, compress_mode="light")

        assert "いま思い出すべき約束" in text
        cue_part = text.split("いま思い出すべき約束", 1)[1]
        assert "面接の約束" in cue_part
        assert "期限切れの約束" not in cue_part

    @pytest.mark.asyncio
    async def test_event_cue_injected_when_entity_mentioned(self):
        from nous.application.chat.pipeline.prepare import _build_context_section

        mem = _mem("m1", "健康診断の結果を聞く", tags=["goal", "active", event_cue_tag("健康診断")])
        turn_ctx = MagicMock()
        turn_ctx.user_message = "明日は健康診断だよ"
        text = await _build_context_section(_ctx([mem]), _state(), turn_ctx, compress_mode="light")
        assert "⚡ [言及] 健康診断の結果を聞く" in text


class TestWorker:
    def test_due_set_recorded_once(self, monkeypatch):
        from nous.application.use_cases import AppContextRegistry
        from nous.application.workers.prospective_worker import ProspectiveWorker

        now = get_now()
        mem = _mem("m1", "面接の約束", tags=["goal", "active", time_cue_tag(now + timedelta(hours=2))])
        ctx = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success([mem])

        inserted: list = []
        monkeypatch.setattr(
            "nous.infrastructure.sqlite.session_event_repo.SessionEventRepository.insert",
            lambda self, event: inserted.append(event),
        )
        monkeypatch.setitem(AppContextRegistry._contexts, "p1", ctx)

        worker = ProspectiveWorker()
        worker.run_cycle()
        worker.run_cycle()

        assert len(inserted) == 1
        assert inserted[0].event_type == "prospective.due"
        assert "近い約束" in inserted[0].summary
