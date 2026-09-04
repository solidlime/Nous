"""Tests for SessionEvent domain entity and repository."""

from __future__ import annotations

from datetime import datetime

import pytest

from nous.domain.memory.session_event import SessionEvent
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(sqlite_conn):
    return SessionEventRepository(sqlite_conn)


# ---------------------------------------------------------------------------
# Domain entity
# ---------------------------------------------------------------------------


class TestSessionEvent:
    def test_create_with_default_timestamp(self):
        event = SessionEvent(
            session_id="sess_001",
            persona="test_persona",
            event_type="tool_call",
            summary="memory_create: hello world",
        )
        assert event.session_id == "sess_001"
        assert event.persona == "test_persona"
        assert event.event_type == "tool_call"
        assert event.summary == "memory_create: hello world"
        assert isinstance(event.timestamp, datetime)
        assert event.detail is None
        assert event.metadata is None
        assert event.id is None

    def test_create_with_all_fields(self):
        ts = datetime(2026, 6, 13, 12, 0, 0)
        event = SessionEvent(
            session_id="sess_002",
            persona="persona_a",
            event_type="chat_message",
            summary="User said hello",
            timestamp=ts,
            detail="Full message content here",
            metadata={"source": "web", "tokens": 42},
            id=99,
        )
        assert event.id == 99
        assert event.timestamp == ts
        assert event.detail == "Full message content here"
        assert event.metadata == {"source": "web", "tokens": 42}


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class TestSessionEventRepository:
    def test_insert_and_get_by_session(self, repo: SessionEventRepository):
        event = SessionEvent(
            session_id="sess_001",
            persona="test_persona",
            event_type="tool_call",
            summary="memory_create: hello",
        )
        row_id = repo.insert(event)
        assert isinstance(row_id, int)
        assert row_id > 0

        events = repo.get_by_session("sess_001")
        assert len(events) == 1
        found = events[0]
        assert found.session_id == "sess_001"
        assert found.persona == "test_persona"
        assert found.event_type == "tool_call"
        assert found.summary == "memory_create: hello"
        assert found.id == row_id

    def test_get_by_session_orders_by_timestamp_desc(self, repo: SessionEventRepository):
        ts1 = datetime(2026, 1, 1, 10, 0, 0)
        ts2 = datetime(2026, 1, 1, 11, 0, 0)
        repo.insert(SessionEvent("sess_002", "p", "tool_call", "first", timestamp=ts1))
        repo.insert(SessionEvent("sess_002", "p", "tool_call", "second", timestamp=ts2))

        events = repo.get_by_session("sess_002")
        assert len(events) == 2
        assert events[0].summary == "second"  # most recent first
        assert events[1].summary == "first"

    def test_get_by_session_limit(self, repo: SessionEventRepository):
        for i in range(5):
            repo.insert(SessionEvent("sess_003", "p", "generic", f"event {i}"))

        all_events = repo.get_by_session("sess_003", limit=3)
        assert len(all_events) == 3

    def test_get_by_persona(self, repo: SessionEventRepository):
        repo.insert(SessionEvent("sess_a", "persona_x", "tool_call", "tool used"))
        repo.insert(SessionEvent("sess_b", "persona_x", "chat_message", "chat msg"))
        repo.insert(SessionEvent("sess_c", "persona_y", "tool_call", "other tool"))

        events = repo.get_by_persona("persona_x")
        assert len(events) == 2

    def test_get_by_persona_with_event_type_filter(self, repo: SessionEventRepository):
        repo.insert(SessionEvent("sess_a", "p", "tool_call", "tool 1"))
        repo.insert(SessionEvent("sess_b", "p", "chat_message", "msg 1"))
        repo.insert(SessionEvent("sess_c", "p", "tool_call", "tool 2"))

        tools = repo.get_by_persona("p", event_type="tool_call")
        assert len(tools) == 2
        for e in tools:
            assert e.event_type == "tool_call"

        msgs = repo.get_by_persona("p", event_type="chat_message")
        assert len(msgs) == 1
        assert msgs[0].event_type == "chat_message"

    def test_metadata_json_serialization(self, repo: SessionEventRepository):
        metadata = {"key": "value", "nested": {"a": 1}, "list": [1, 2, 3]}
        event = SessionEvent(
            session_id="sess_meta",
            persona="p",
            event_type="tool_call",
            summary="with metadata",
            metadata=metadata,
        )
        _ = repo.insert(event)

        # Read back and verify metadata is preserved
        events = repo.get_by_session("sess_meta")
        assert len(events) == 1
        found = events[0]
        assert found.metadata == metadata

    def test_metadata_none(self, repo: SessionEventRepository):
        event = SessionEvent(
            session_id="sess_nometa",
            persona="p",
            event_type="generic",
            summary="no metadata",
        )
        repo.insert(event)
        events = repo.get_by_session("sess_nometa")
        assert events[0].metadata is None

    def test_detail_field(self, repo: SessionEventRepository):
        event = SessionEvent(
            session_id="sess_detail",
            persona="p",
            event_type="chat_message",
            summary="msg summary",
            detail="This is a longer detail string with more information.",
        )
        repo.insert(event)
        events = repo.get_by_session("sess_detail")
        assert events[0].detail == "This is a longer detail string with more information."

    def test_empty_db_returns_empty_list(self, repo: SessionEventRepository):
        assert repo.get_by_session("nonexistent") == []
        assert repo.get_by_persona("nonexistent") == []
