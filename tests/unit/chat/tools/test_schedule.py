"""schedule_task（kanban #36）のテスト: when パース / recur / タグの入れ替え。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.tools import schedule
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Failure, Success

NOW = datetime(2026, 11, 18, 9, 0)


def _memory(tags: list[str], content: str = "日記を書く") -> Memory:
    return Memory(key="mem_1", content=content, created_at=NOW, updated_at=NOW, tags=list(tags))


def _ctx(create_result=None) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "test"
    ctx.memory_service.create_memory = AsyncMock(
        return_value=Success(_memory([schedule.AGENT_TASK_TAG])) if create_result is None else create_result
    )
    return ctx


class TestParseWhen:
    def test_iso_datetime(self) -> None:
        assert schedule.parse_when("2026-11-20T07:30", NOW) == datetime(2026, 11, 20, 7, 30)

    def test_iso_with_z(self) -> None:
        assert schedule.parse_when("2026-11-20T07:30Z", NOW) == datetime(2026, 11, 20, 7, 30, tzinfo=UTC)

    def test_date_only_anchors_at_nine(self) -> None:
        # cue.parse_deadline の規則（"tomorrow" が "5分後" にならない）
        assert schedule.parse_when("2026-11-20", NOW) == datetime(2026, 11, 20, 9, 0)

    @pytest.mark.parametrize(
        ("text", "delta"),
        [("+2h", timedelta(hours=2)), ("+30m", timedelta(minutes=30)), ("+3d", timedelta(days=3))],
    )
    def test_relative(self, text: str, delta: timedelta) -> None:
        assert schedule.parse_when(text, NOW) == NOW + delta

    @pytest.mark.parametrize("text", ["", "  ", "tomorrow", "+0h", "-2h", "+2x", "abc", None, 3])
    def test_junk_is_none(self, text: object) -> None:
        assert schedule.parse_when(text, NOW) is None


class TestScheduleTask:
    async def test_tags_and_due(self) -> None:
        ctx = _ctx()
        out = await schedule.schedule_task(ctx, "2026-11-20T07:30", "日記を書く", now=NOW)
        assert out["status"] == "ok"
        assert out["due"] == "2026-11-20T07:30"
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["content"] == "日記を書く"
        assert kwargs["tags"] == [schedule.AGENT_TASK_TAG, "cue:time:2026-11-20T07:30:00"]

    async def test_relative_when_and_recur(self) -> None:
        ctx = _ctx()
        out = await schedule.schedule_task(ctx, "+2h", "散歩", recur="daily", now=NOW)
        assert out["status"] == "ok"
        assert out["due"] == "2026-11-18T11:00"
        assert ctx.memory_service.create_memory.await_args.kwargs["tags"] == [
            schedule.AGENT_TASK_TAG,
            "cue:time:2026-11-18T11:00:00",
            "cue:recur:daily",
        ]

    @pytest.mark.parametrize(
        ("when", "prompt", "recur"),
        [("いつか", "x", None), ("", "x", None), ("+1h", "", None), ("+1h", "x", "hourly")],
    )
    async def test_bad_input_is_error(self, when: str, prompt: str, recur: str | None) -> None:
        ctx = _ctx()
        out = await schedule.schedule_task(ctx, when, prompt, recur=recur, now=NOW)
        assert out["status"] == "error"
        ctx.memory_service.create_memory.assert_not_awaited()

    async def test_memory_failure_is_error(self) -> None:
        ctx = _ctx(create_result=Failure(RuntimeError("db down")))
        out = await schedule.schedule_task(ctx, "+1h", "x", now=NOW)
        assert out["status"] == "error"
        assert "db down" in out["message"]

    async def test_handler_reads_tool_input(self) -> None:
        ctx = _ctx()
        out = await schedule.handle_schedule_task(ctx, None, {"when": "+1h", "prompt": "x"})
        assert out["status"] == "ok"
        assert out["message"].startswith("予定を登録した: x @ ")
        tags = ctx.memory_service.create_memory.await_args.kwargs["tags"]
        assert tags[0] == schedule.AGENT_TASK_TAG and tags[1].startswith("cue:time:")


class TestDueAndTags:
    def test_future_task_is_not_due(self) -> None:
        task = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T12:00"])
        assert schedule.due_agent_tasks([task], NOW) == []

    def test_due_and_overdue_are_due(self) -> None:
        due = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T09:00"])
        overdue = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-17T09:00"])
        assert schedule.due_agent_tasks([due, overdue], NOW) == [due, overdue]

    def test_overdue_beyond_72h_grace_is_dropped(self) -> None:
        """docstring の主張（過期は OVERDUE_GRACE_HOURS=72h 内のみ）を固定する境界テスト（#68）。"""
        edge = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-15T09:00"], content="ちょうど72h")
        stale = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-15T08:00"], content="73h前")
        assert schedule.due_agent_tasks([edge, stale], NOW) == [edge]

    def test_missing_agent_tag_is_ignored(self) -> None:
        assert schedule.due_agent_tasks([_memory(["cue:time:2026-11-18T09:00"])], NOW) == []

    def test_recur_of(self) -> None:
        assert schedule.recur_of(_memory(["cue:recur:weekly"])) == "weekly"
        assert schedule.recur_of(_memory(["cue:recur:hourly"])) is None
        assert schedule.recur_of(_memory([])) is None

    def test_done_tags_strip_everything_for_one_shot(self) -> None:
        task = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T09:00", "agent:task:fail:1", "work"])
        assert schedule.done_tags(task, None, NOW) == ["work"]

    def test_done_tags_reinsert_next_cue_for_recur(self) -> None:
        task = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T09:00", "cue:recur:daily"])
        tags = schedule.done_tags(task, "daily", NOW)
        assert tags == [schedule.AGENT_TASK_TAG, "cue:time:2026-11-19T09:00:00", "cue:recur:daily"]

    def test_retry_tags_keep_cue(self) -> None:
        task = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T09:00", "cue:recur:weekly"])
        assert schedule.retry_tags(task, 2) == [
            schedule.AGENT_TASK_TAG,
            "cue:time:2026-11-18T09:00",
            "cue:recur:weekly",
            "agent:task:fail:2",
        ]

    def test_next_due_skips_missed_cycles(self) -> None:
        # 1週間止まっていた weekly は1回で追いつく（過去の分を何周も回さない）
        assert schedule.next_due(datetime(2026, 11, 1, 9, 0), "weekly", NOW) == datetime(2026, 11, 22, 9, 0)


class TestMixedTimezone:
    """cue タグは naive・get_now() は aware（#84）。"""

    def test_done_tags_handles_naive_cue_with_aware_now(self) -> None:
        task = _memory([schedule.AGENT_TASK_TAG, "cue:time:2026-11-18T09:00", "cue:recur:daily"])
        aware_now = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
        tags = schedule.done_tags(task, "daily", aware_now)
        assert tags == [schedule.AGENT_TASK_TAG, "cue:time:2026-11-19T09:00:00", "cue:recur:daily"]

    def test_next_due_handles_naive_deadline_with_aware_now(self) -> None:
        aware_now = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
        nxt = schedule.next_due(datetime(2026, 11, 17, 9, 0), "daily", aware_now)
        assert nxt == datetime(2026, 11, 19, 9, 0)
