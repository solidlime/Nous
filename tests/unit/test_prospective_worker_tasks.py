"""ProspectiveWorker の agent:task 実行（kanban #36）のテスト。"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.tools import schedule
from nous.application.workers import prospective_worker
from nous.domain.memory.cue import time_cue_tag
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

PERSONA = "test"


def _memory(tags: list[str], content: str = "日記を書く") -> Memory:
    now = get_now()
    return Memory(key="mem_1", content=content, created_at=now, updated_at=now, tags=list(tags))


@pytest.fixture
def ctx(sqlite_conn):
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = sqlite_conn
    ctx.memory_service.update_memory = MagicMock(return_value=Success(_memory([])))
    return ctx


@pytest.fixture
def worker(monkeypatch, ctx):
    from nous.application.use_cases import AppContextRegistry

    monkeypatch.setattr(AppContextRegistry, "personas", classmethod(lambda cls: [PERSONA]))
    monkeypatch.setattr(AppContextRegistry, "get", classmethod(lambda cls, persona: ctx))
    turn = AsyncMock(return_value=None)
    monkeypatch.setattr(prospective_worker, "run_self_turn", turn)
    return prospective_worker.ProspectiveWorker(), turn


def _due_tags() -> list[str]:
    return [schedule.AGENT_TASK_TAG, time_cue_tag(get_now() - timedelta(minutes=1))]


def _events(ctx) -> list[str]:
    return [e.event_type for e in SessionEventRepository(ctx.connection).get_by_persona(PERSONA, limit=20)]


class TestRunAgentTasks:
    def test_one_shot_runs_once_and_drops_tag(self, worker, ctx) -> None:
        w, turn = worker
        task = _memory(_due_tags(), "日記を書く")
        ctx.memory_service.get_by_tags.return_value = Success([task])

        w.run_agent_tasks()

        turn.assert_awaited_once()
        assert turn.await_args.args[1] == "[自分で決めた予定] 日記を書く"
        ctx.memory_service.update_memory.assert_called_once_with("mem_1", tags=[])
        assert "agent.task.ran" in _events(ctx)

    def test_future_task_is_not_run(self, worker, ctx) -> None:
        w, turn = worker
        future = _memory([schedule.AGENT_TASK_TAG, time_cue_tag(get_now() + timedelta(hours=2))])
        ctx.memory_service.get_by_tags.return_value = Success([future])

        w.run_agent_tasks()

        turn.assert_not_awaited()
        ctx.memory_service.update_memory.assert_not_called()

    def test_recur_reinserts_next_cue(self, worker, ctx) -> None:
        w, _turn = worker
        tomorrow = get_now() + timedelta(days=1)
        task = _memory([*_due_tags(), "cue:recur:daily"])
        ctx.memory_service.get_by_tags.return_value = Success([task])

        w.run_agent_tasks()

        tags = ctx.memory_service.update_memory.call_args.kwargs["tags"]
        assert tags[0] == schedule.AGENT_TASK_TAG
        assert tags[1].startswith("cue:time:")
        assert schedule.parse_deadline(tags[1][len("cue:time:") :]) > tomorrow - timedelta(minutes=5)
        assert "cue:recur:daily" in tags

    def test_failure_keeps_task_and_counts(self, worker, ctx) -> None:
        w, turn = worker
        turn.side_effect = RuntimeError("llm down")
        ctx.memory_service.get_by_tags.return_value = Success([_memory(_due_tags())])

        w.run_agent_tasks()

        tags = ctx.memory_service.update_memory.call_args.kwargs["tags"]
        assert schedule.AGENT_TASK_TAG in tags
        assert "agent:task:fail:1" in tags
        assert "agent.task.failed" in _events(ctx)

    def test_third_failure_gives_up(self, worker, ctx) -> None:
        w, turn = worker
        turn.side_effect = RuntimeError("llm down")
        task = _memory([*_due_tags(), "agent:task:fail:2"])
        ctx.memory_service.get_by_tags.return_value = Success([task])

        w.run_agent_tasks()

        assert ctx.memory_service.update_memory.call_args.kwargs["tags"] == []
        summary = SessionEventRepository(ctx.connection).get_by_persona(PERSONA, limit=5)[0].summary
        assert "(3/3)" in summary

    def test_no_due_tasks_does_nothing(self, worker, ctx) -> None:
        w, turn = worker
        ctx.memory_service.get_by_tags.return_value = Success([])

        w.run_agent_tasks()

        turn.assert_not_awaited()
        ctx.memory_service.update_memory.assert_not_called()
