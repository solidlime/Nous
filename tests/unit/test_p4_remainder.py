"""P4 remainder tests — M1 interference / M2 sweep / M3 metamemory / M4 temporal links / L2 task context."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory.cue import DUE_REMINDER_TAG, time_cue_tag
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Failure, Success


def _mem(key: str, content: str = "内容", tags: list[str] | None = None, **kwargs) -> Memory:
    now = datetime(2026, 9, 19, 12, 0)
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.7, tags=tags or [], **kwargs)


# ===========================================================================
# M2 — hourly prospective sweep
# ===========================================================================


class TestDueCueSweep:
    def _worker(self, due_memories, existing=None):
        from nous.application.workers.decay_worker import DecayWorker

        ctx = MagicMock()
        ctx.persona = "p1"
        ctx.memory_service.get_by_tags.side_effect = lambda tags: (
            Success(due_memories) if "goal" in tags else Success(existing or [])
        )
        ctx.memory_repo.save.return_value = Success(None)
        return DecayWorker(ctx), ctx

    def test_due_commitment_queues_reminder(self):
        now = datetime.now()
        goal = _mem("g1", "面接に行く", tags=["goal", "active", time_cue_tag(now + timedelta(hours=2))])
        worker, ctx = self._worker([goal])
        worker._due_cue_cycle()
        assert ctx.memory_repo.save.call_count == 1
        reminder = ctx.memory_repo.save.call_args[0][0]
        assert reminder.tags == [DUE_REMINDER_TAG]
        assert "面接に行く" in reminder.content

    def test_no_due_commitment_saves_nothing(self):
        goal = _mem("g1", "遠い目標", tags=["goal", "active", time_cue_tag(datetime.now() + timedelta(days=30))])
        worker, ctx = self._worker([goal])
        worker._due_cue_cycle()
        ctx.memory_repo.save.assert_not_called()

    def test_unconsumed_reminder_is_not_restacked(self):
        now = datetime.now()
        goal = _mem("g1", "面接に行く", tags=["goal", "active", time_cue_tag(now + timedelta(hours=2))])
        first, ctx = self._worker([goal])
        first._due_cue_cycle()
        content = ctx.memory_repo.save.call_args[0][0].content
        existing = _mem("due_reminder_p1_x", content, tags=[DUE_REMINDER_TAG])
        second, ctx2 = self._worker([goal], existing=[existing])
        second._due_cue_cycle()
        ctx2.memory_repo.save.assert_not_called()

    def test_cycle_runs_sweep_after_decay(self):
        worker, ctx = self._worker([])
        with patch.object(worker, "_decay_cycle") as decay, patch.object(worker, "_due_cue_cycle") as sweep:
            worker._run_cycle()
        decay.assert_called_once()
        sweep.assert_called_once()


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

    def test_health_label_from_retrievability(self):
        from nous.api.mcp._tools_memory import _compute_retrievability_health

        ctx = MagicMock()
        strength = MagicMock()
        strength.last_decay = None
        strength.compute_recall.return_value = 0.9
        ctx.memory_repo.get_all_strengths.return_value = Success([strength])
        health = _compute_retrievability_health(ctx)
        assert health is not None
        assert health["label"] == "healthy"
        assert health["counted"] == 1

    def test_health_critical_when_decayed(self):
        from nous.api.mcp._tools_memory import _compute_retrievability_health

        ctx = MagicMock()
        strength = MagicMock()
        strength.last_decay = datetime.now() - timedelta(days=90)
        strength.compute_recall.return_value = 0.1
        ctx.memory_repo.get_all_strengths.return_value = Success([strength])
        assert _compute_retrievability_health(ctx)["label"] == "critical"

    def test_health_none_without_data(self):
        from nous.api.mcp._tools_memory import _compute_retrievability_health

        ctx = MagicMock()
        ctx.memory_repo.get_all_strengths.return_value = Success([])
        assert _compute_retrievability_health(ctx) is None

    @pytest.mark.asyncio
    async def test_stats_include_health(self):
        from nous.api.mcp._tools_memory import _tool_memory_stats

        ctx = MagicMock()
        ctx.memory_service.get_stats.return_value = Success({"total": 3})
        strength = MagicMock()
        strength.last_decay = None
        strength.compute_recall.return_value = 0.8
        ctx.memory_repo.get_all_strengths.return_value = Success([strength])
        ctx.event_bus.publish = AsyncMock()
        out = json.loads(await _tool_memory_stats(ctx, "p1"))
        assert out["data"]["retrievability_health"]["label"] == "healthy"
        assert out["data"]["total"] == 3


# ===========================================================================
# M1 — interference
# ===========================================================================


class TestInterference:
    def _service(self):
        from nous.domain.memory.evolution_service import MemoryEvolutionService

        repo = MagicMock()
        strength = MagicMock()
        strength.interference_count = 0
        repo.get_strength.return_value = Success(strength)
        repo.find_by_key.return_value = Success(None)
        repo.save.return_value = Success(None)
        return MemoryEvolutionService([], repo, None, None, None), repo, strength

    def test_similar_neighbour_bumps_count(self):
        service, repo, strength = self._service()
        service._register_interference("old", "new", 0.9)
        assert strength.interference_count == 1
        repo.save_strength.assert_called_once_with(strength)
        repo.save.assert_not_called()

    def test_below_band_is_ignored(self):
        service, repo, _ = self._service()
        service._register_interference("old", "new", 0.5)
        repo.save_strength.assert_not_called()

    def test_above_band_is_ignored(self):
        service, repo, _ = self._service()
        service._register_interference("old", "new", 0.99)
        repo.save_strength.assert_not_called()

    def test_threshold_queues_review_once(self):
        service, repo, strength = self._service()
        strength.interference_count = 2  # this bump reaches the threshold
        service._register_interference("old", "new", 0.9)
        assert repo.save.call_count == 1
        marker = repo.save.call_args[0][0]
        assert marker.tags == ["interference_review"]
        assert "old" in marker.content and "new" in marker.content

    def test_missing_strength_row_is_survivable(self):
        service, repo, _ = self._service()
        repo.get_strength.return_value = Failure(MagicMock())
        service._register_interference("old", "new", 0.9)  # must not raise
        repo.save_strength.assert_not_called()


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
