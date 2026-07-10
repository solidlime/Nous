"""Tests for _build_relationship_context and relationship context injection in PromptBuildStep."""

from __future__ import annotations

import datetime as dt_module
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from nous.application.chat.pipeline.prepare import _build_relationship_context
from nous.application.chat.pipeline.prompt import PromptBuildStep

# Fixed reference "now" for all tests
REF_NOW = dt_module.datetime(2026, 7, 10, 12, 0, 0, tzinfo=dt_module.UTC)


def _sqlite_dt(dt: dt_module.datetime) -> str:
    """Format a datetime as SQLite datetime('now') would return (no tz, space separator)."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class FakeDatetime:
    """Stand-in for datetime class: real fromisoformat, controlled now()."""

    def __init__(self, *args, **kwargs):
        # Allow instantiation by delegating to real datetime
        self._real = dt_module.datetime(*args, **kwargs)

    @classmethod
    def now(cls, tz=None):
        return REF_NOW

    @classmethod
    def fromisoformat(cls, date_string):
        return dt_module.datetime.fromisoformat(date_string)

    @classmethod
    def combine(cls, *args, **kwargs):
        return dt_module.datetime.combine(*args, **kwargs)

    @classmethod
    def strptime(cls, *args, **kwargs):
        return dt_module.datetime.strptime(*args, **kwargs)


def _make_ctx(db, persona: str = "test_persona"):
    ctx = MagicMock()
    ctx.persona = persona
    conn = MagicMock()
    conn.get_memory_db.return_value = db
    ctx.connection = conn
    return ctx


@pytest.fixture(autouse=True)
def _patch_datetime():
    with patch("nous.application.chat.pipeline.prepare.datetime", FakeDatetime):
        yield


class MockDb:
    """Mock SQLite connection returning controlled values for prompt queries."""

    def __init__(self, first_at: str | None = None, active_days: int = 0, last_time: str | None = None):
        self._first_at = first_at
        self._active_days = active_days
        self._last_time = last_time

    def execute(self, sql: str, params: tuple = ()) -> MagicMock:
        cursor = MagicMock()
        sql_upper = sql.upper()
        if "MIN(CREATED_AT)" in sql_upper:
            cursor.fetchone.return_value = (self._first_at,)
        elif "COUNT(DISTINCT DATE(CREATED_AT))" in sql_upper:
            cursor.fetchone.return_value = (self._active_days,)
        elif "LAST_CONVERSATION_TIME" in sql_upper and "VALID_UNTIL" in sql_upper:
            cursor.fetchone.return_value = (self._last_time,)
        else:
            cursor.fetchone.return_value = None
        return cursor


class TestBuildRelationshipContext:
    """Tests for _build_relationship_context function."""

    def test_no_history_returns_empty(self):
        """Empty session_events -> empty string returned."""
        db = MockDb(first_at=None)
        result = _build_relationship_context(_make_ctx(db))
        assert result == ""

    def test_first_conversation(self):
        """Single event just created -> '初めて会話する' text."""
        first_at = _sqlite_dt(REF_NOW)
        db = MockDb(first_at=first_at, active_days=1)
        result = _build_relationship_context(_make_ctx(db))
        assert "初めて会話する" in result

    def test_known_for_several_days(self):
        """Events spanning multiple days -> correct days count."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=5))
        db = MockDb(first_at=first_at, active_days=3)
        result = _build_relationship_context(_make_ctx(db))
        assert "5日前から知り合い" in result
        assert "3 日会話した" in result

    def test_days_since_last(self):
        """last_conversation_time from yesterday -> '1日経過' text."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=10))
        last_time = _sqlite_dt(REF_NOW - timedelta(days=1))
        db = MockDb(first_at=first_at, active_days=5, last_time=last_time)
        result = _build_relationship_context(_make_ctx(db))
        assert "前回の会話から1日経過" in result

    def test_long_absence(self):
        """last_conversation_time from 30+ days ago -> '長い間' text."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=60))
        last_time = _sqlite_dt(REF_NOW - timedelta(days=35))
        db = MockDb(first_at=first_at, active_days=10, last_time=last_time)
        result = _build_relationship_context(_make_ctx(db))
        assert "長い間話していなかった" in result

    def test_active_days_count(self):
        """DISTINCT dates count works correctly."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=30))
        db = MockDb(first_at=first_at, active_days=7)
        result = _build_relationship_context(_make_ctx(db))
        assert "7 日会話した" in result

    def test_days_since_last_same_day_skipped(self):
        """days_since_last == 0 (same day) -> no '経過' line."""
        first_at = _sqlite_dt(REF_NOW)
        last_time = _sqlite_dt(REF_NOW)
        db = MockDb(first_at=first_at, active_days=1, last_time=last_time)
        result = _build_relationship_context(_make_ctx(db))
        assert "経過" not in result

    def test_days_since_last_under_seven(self):
        """days_since_last between 2-6 -> simple count without extra note."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=20))
        last_time = _sqlite_dt(REF_NOW - timedelta(days=3))
        db = MockDb(first_at=first_at, active_days=8, last_time=last_time)
        result = _build_relationship_context(_make_ctx(db))
        assert "前回の会話から3日経過。" in result
        assert "しばらく" not in result
        assert "長い間" not in result

    def test_days_since_last_under_thirty(self):
        """days_since_last between 7-29 -> includes 'しばらく' note."""
        first_at = _sqlite_dt(REF_NOW - timedelta(days=50))
        last_time = _sqlite_dt(REF_NOW - timedelta(days=14))
        db = MockDb(first_at=first_at, active_days=15, last_time=last_time)
        result = _build_relationship_context(_make_ctx(db))
        assert "前回の会話から14日経過。" in result
        assert "しばらく話していない" in result

    def test_context_appended_to_prompt(self):
        """Verify relationship context in context_section flows into system_prompt."""
        # Relationship context is now injected into context_section by _build_context_section().
        # Simulate that output here to verify PromptBuildStep includes it.
        ctx = MagicMock()
        ctx.persona = "test_persona"

        config = MagicMock()
        config.system_prompt = "あなたはアシスタントです。"
        config.enabled_skills = []

        turn_ctx = MagicMock()
        turn_ctx.context_section = (
            "【現在の状態】\nNow: 2026-07-10 12:00 (JST)\n\n"
            "【身体・環境】\n"
            "関係: 友好的\n"
            "3日前から知り合い。これまで 2 日会話した。\n\n"
            "【参照情報】\n"
        )
        turn_ctx.related_memories = ""
        turn_ctx.author_note = None
        turn_ctx.system_prompt = ""
        turn_ctx.skills_raw = []

        step = PromptBuildStep()
        step.run(ctx, config, turn_ctx)

        # Header is stripped in prepare.py integration; content should be in prompt
        assert "関係性コンテキスト" not in turn_ctx.system_prompt
        assert "3日前から知り合い" in turn_ctx.system_prompt
        assert "2 日会話した" in turn_ctx.system_prompt
