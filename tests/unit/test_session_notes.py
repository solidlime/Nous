"""session_begin の notes — 沈黙の間（#37）と約束（#43）のテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application import session_notes
from nous.domain.memory.cue import PROMISE_TAGS
from nous.domain.memory.entities import Memory
from nous.domain.memory.session_event import SessionEvent
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

PERSONA = "test"
HF = 0.5


def _ctx(conn, memories: list[Memory] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = conn
    ctx.memory_service.get_by_tags.return_value = Success(memories or [])
    ctx.memory_service.create_memory = AsyncMock(return_value=Success(_memory(["life:between"])))
    ctx.config = MagicMock()
    return ctx


def _memory(tags: list[str], content: str = "出かけた") -> Memory:
    now = get_now()
    return Memory(key="mem_1", content=content, created_at=now, updated_at=now, tags=list(tags))


def _stop(conn, hours_ago: float) -> None:
    SessionEventRepository(conn).insert(
        SessionEvent(
            session_id="main",
            persona=PERSONA,
            event_type="session.stopped",
            timestamp=get_now() - timedelta(hours=hours_ago),
            summary="bye",
        )
    )


@pytest.fixture
def generate(monkeypatch):
    """LLM 呼び出しを差し替え（既定は成功）。"""
    stub = AsyncMock(return_value="昼まで寝て、そのあと散歩した。")
    monkeypatch.setattr(session_notes, "_generate", stub)
    return stub


class TestSilenceBoundary:
    async def test_no_previous_session_does_nothing(self, sqlite_conn, generate) -> None:
        ctx = _ctx(sqlite_conn)
        assert await session_notes.fill_silence(ctx, PERSONA, 6.0) is None
        generate.assert_not_awaited()

    async def test_below_threshold_does_nothing(self, sqlite_conn, generate) -> None:
        _stop(sqlite_conn, 5.9)
        ctx = _ctx(sqlite_conn)
        assert await session_notes.fill_silence(ctx, PERSONA, 6.0) is None
        generate.assert_not_awaited()

    async def test_at_threshold_stores_one_memory(self, sqlite_conn, generate) -> None:
        _stop(sqlite_conn, 6.05)
        ctx = _ctx(sqlite_conn)
        assert await session_notes.fill_silence(ctx, PERSONA, 6.0) is None
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["life:between"]
        assert "散歩" in kwargs["content"]

    async def test_llm_failure_returns_warning_line(self, sqlite_conn, generate) -> None:
        _stop(sqlite_conn, 30)
        generate.return_value = None
        ctx = _ctx(sqlite_conn)
        note = await session_notes.fill_silence(ctx, PERSONA, 6.0)
        assert note is not None and note.startswith("warning:")
        ctx.memory_service.create_memory.assert_not_awaited()

    async def test_store_failure_returns_warning_line(self, sqlite_conn, generate) -> None:
        _stop(sqlite_conn, 30)
        ctx = _ctx(sqlite_conn)
        ctx.memory_service.create_memory = AsyncMock(return_value=MagicMock(is_ok=False, error="db down"))
        note = await session_notes.fill_silence(ctx, PERSONA, 6.0)
        assert note == "warning: silence memory not stored: db down"

    async def test_no_config_gives_warning_not_raise(self, sqlite_conn, monkeypatch) -> None:
        _stop(sqlite_conn, 30)
        ctx = _ctx(sqlite_conn)
        ctx.config = None
        note = await session_notes.fill_silence(ctx, PERSONA, 6.0)
        assert note is not None and note.startswith("warning:")


class TestHoursSince:
    def test_naive_timestamp_is_comparable(self) -> None:
        now = datetime(2026, 11, 18, 9, 0)
        assert session_notes._hours_since(datetime(2026, 11, 18, 3, 0), now) == 6.0


class TestPromiseNote:
    def test_due_promise_gives_one_line(self, sqlite_conn) -> None:
        due = get_now() + timedelta(hours=3)
        memory = _memory(["promise", f"cue:time:{due.isoformat(timespec='minutes')}"], "健診の結果を聞く")
        ctx = _ctx(sqlite_conn, [memory])
        note = session_notes.promise_note(ctx)
        # 書き手（memory_extractor）と同じタグ組で引いていること
        ctx.memory_service.get_by_tags.assert_called_once_with(list(PROMISE_TAGS))
        assert note is not None
        assert note.startswith("⏳ 自分から切り出す: 健診の結果を聞く")
        assert "in 3h" in note

    def test_promise_without_cue_is_ignored(self, sqlite_conn) -> None:
        ctx = _ctx(sqlite_conn, [_memory(["promise"], "いつか話す")])
        assert session_notes.promise_note(ctx) is None

    def test_far_future_promise_is_ignored(self, sqlite_conn) -> None:
        due = get_now() + timedelta(days=10)
        memory = _memory(["promise", f"cue:time:{due.isoformat(timespec='minutes')}"])
        ctx = _ctx(sqlite_conn, [memory])
        assert session_notes.promise_note(ctx) is None

    def test_lookup_failure_is_silent(self, sqlite_conn) -> None:
        ctx = _ctx(sqlite_conn)
        ctx.memory_service.get_by_tags.side_effect = RuntimeError("db down")
        assert session_notes.promise_note(ctx) is None
