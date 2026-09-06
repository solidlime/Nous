"""Tests for SessionEventRecorder."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from nous.application.session_event_recorder import SessionEventRecorder
from nous.domain.memory.session_event import SessionEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_event_bus():
    return MagicMock()


@pytest.fixture
def mock_repo():
    return MagicMock()


@pytest.fixture
def recorder(mock_event_bus, mock_repo):
    return SessionEventRecorder(mock_event_bus, mock_repo)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSessionEventRecorder:
    """Tests for SessionEventRecorder."""

    def test_init(self, recorder, mock_event_bus, mock_repo):
        """Verify recorder is created with correct dependencies."""
        assert recorder._event_bus is mock_event_bus
        assert recorder._repo is mock_repo

    def test_start_subscribes(self, recorder, mock_event_bus):
        """Verify subscribe called for each event type."""
        recorder.start()

        expected_types = [
            "tool.called",
            "events.ingested",
            "chat.message",
            "chat.llm_response",
            "session.started",
            "session.compact",
        ]
        actual_calls = mock_event_bus.subscribe.call_args_list
        assert len(actual_calls) == len(expected_types)

        for (args, _kwargs), exp_type in zip(actual_calls, expected_types, strict=True):
            assert args[0] == exp_type
            # Verify the handler is _on_event bound to this recorder instance
            assert args[1].__self__ is recorder
            assert args[1].__func__ is SessionEventRecorder._on_event

    @pytest.mark.asyncio
    async def test_on_event_inserts(self, recorder, mock_repo):
        """Verify _on_event calls repo.insert with correct SessionEvent."""
        data = {
            "session_id": "sess_001",
            "persona": "test_persona",
            "timestamp": "2026-06-13T10:30:00",
            "tool_name": "memory_create",
            "params_summary": '{"content": "hello"}',
            "result_summary": "created memory key_abc",
            "success": True,
            "detail": "some detail",
            "metadata": {"source": "test"},
        }

        await recorder._on_event("tool.called", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]

        assert isinstance(event, SessionEvent)
        assert event.session_id == "sess_001"
        assert event.persona == "test_persona"
        assert event.event_type == "tool.called"
        assert event.summary == "memory_create: ✓ created memory key_abc"
        assert event.timestamp == datetime(2026, 6, 13, 10, 30, 0)
        assert event.detail == "some detail"
        assert event.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_on_event_inserts_events_ingested(self, recorder, mock_repo):
        """Verify _on_event handles events.ingested correctly."""
        data = {
            "session_id": "sess_002",
            "persona": "test_persona",
            "events": [{"type": "chat"}, {"type": "tool"}],
        }

        await recorder._on_event("events.ingested", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.event_type == "events.ingested"
        assert event.summary == "Plugin ingested 2 events"

    @pytest.mark.asyncio
    async def test_on_event_skips_unknown(self, recorder, mock_repo):
        """Verify unrecognized event types don't crash."""
        data = {
            "session_id": "sess_003",
            "persona": "test_persona",
        }

        await recorder._on_event("unknown.event", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.event_type == "unknown.event"
        assert event.summary == "unknown.event: "

    @pytest.mark.asyncio
    async def test_on_event_missing_fields(self, recorder, mock_repo):
        """Verify missing fields use sensible defaults."""
        data = {}

        await recorder._on_event("tool.called", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.session_id == "unknown"
        assert event.persona == "unknown"
        assert event.event_type == "tool.called"
        assert event.summary == "unknown: ✓"

    @pytest.mark.asyncio
    async def test_on_event_handles_error(self, recorder, mock_repo):
        """Verify repo error doesn't propagate (logged only)."""
        mock_repo.insert.side_effect = RuntimeError("DB failure")

        data = {
            "session_id": "sess_004",
            "persona": "test_persona",
            "timestamp": "2026-06-13T12:00:00",
        }

        # Should not raise
        await recorder._on_event("tool.called", data)

        mock_repo.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_event_invalid_timestamp(self, recorder, mock_repo):
        """Verify invalid timestamp falls back to get_now()."""
        with patch("nous.application.session_event_recorder.get_now") as mock_get_now:
            fake_now = datetime(2026, 6, 13, 15, 0, 0)
            mock_get_now.return_value = fake_now

            data = {
                "session_id": "sess_005",
                "persona": "test_persona",
                "timestamp": "not-a-valid-timestamp",
            }

            await recorder._on_event("tool.called", data)

            mock_repo.insert.assert_called_once()
            event: SessionEvent = mock_repo.insert.call_args[0][0]
            assert event.timestamp == fake_now

    def test_build_summary_tool_called(self, recorder):
        """Verify _build_summary for tool.called events."""
        # Success case
        summary = recorder._build_summary(
            "tool.called",
            {
                "tool_name": "memory_search",
                "result_summary": "found 3 results",
                "success": True,
            },
        )
        assert summary == "memory_search: ✓ found 3 results"

        # Failure case
        summary = recorder._build_summary(
            "tool.called",
            {
                "tool_name": "memory_search",
                "result_summary": "timeout",
                "success": False,
            },
        )
        assert summary == "memory_search: ✗ timeout"

        # No result
        summary = recorder._build_summary(
            "tool.called",
            {
                "tool_name": "memory_search",
                "success": True,
            },
        )
        assert summary == "memory_search: ✓"

    def test_build_summary_events_ingested(self, recorder):
        """Verify _build_summary for events.ingested."""
        summary = recorder._build_summary(
            "events.ingested",
            {
                "events": [{"type": "a"}, {"type": "b"}, {"type": "c"}],
            },
        )
        assert summary == "Plugin ingested 3 events"

        # Empty events list
        summary = recorder._build_summary("events.ingested", {"events": []})
        assert summary == "Plugin ingested 0 events"

    def test_build_summary_unknown(self, recorder):
        """Verify _build_summary for unknown event types."""
        summary = recorder._build_summary("custom.event", {"summary": "hello world"})
        assert summary == "custom.event: hello world"

    def test_build_summary_chat_message(self, recorder):
        """Verify _build_summary for chat.message."""
        summary = recorder._build_summary(
            "chat.message",
            {
                "content": "Hello, how are you?",
            },
        )
        assert summary == "💬 Hello, how are you?"

        # Long content truncated
        long_content = "A" * 200
        summary = recorder._build_summary(
            "chat.message",
            {
                "content": long_content,
            },
        )
        assert summary == "💬 " + "A" * 100
        assert len(summary) == 102  # emoji (1) + space (1) + 100 chars

    def test_build_summary_chat_llm_response(self, recorder):
        """Verify _build_summary for chat.llm_response."""
        summary = recorder._build_summary(
            "chat.llm_response",
            {
                "content": "I am fine, thank you!",
            },
        )
        assert summary == "🤖 I am fine, thank you!"

        # Long content truncated
        summary = recorder._build_summary(
            "chat.llm_response",
            {
                "content": "B" * 150,
            },
        )
        assert summary == "🤖 " + "B" * 100

    def test_build_summary_session_compact(self, recorder):
        """Verify _build_summary for session.compact."""
        summary = recorder._build_summary(
            "session.compact",
            {
                "before_tokens": 5000,
                "after_tokens": 2000,
            },
        )
        assert summary == "📦 Compressed: 5000→2000 tokens"

    def test_build_summary_session_started(self, recorder):
        """Verify _build_summary for session.started."""
        summary = recorder._build_summary(
            "session.started",
            {
                "session_id": "sess_abc",
            },
        )
        assert summary == "▶ Session started: sess_abc"

    @pytest.mark.asyncio
    async def test_on_event_session_id_none_falls_back(self, recorder, mock_repo):
        """Explicit None session_id must not violate NOT NULL — falls back to 'unknown'."""
        data = {
            "session_id": None,
            "persona": "test_persona",
            "tool_name": "memory_search",
            "success": True,
        }

        await recorder._on_event("tool.called", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.session_id == "unknown"

    @pytest.mark.asyncio
    async def test_on_event_inserts_chat_message(self, recorder, mock_repo):
        """Verify _on_event handles chat.message correctly."""
        data = {
            "session_id": "sess_chat_001",
            "persona": "test_persona",
            "content": "Hello world",
            "timestamp": "2026-06-13T10:30:00",
        }

        await recorder._on_event("chat.message", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.event_type == "chat.message"
        assert event.summary == "💬 Hello world"
        assert event.session_id == "sess_chat_001"
        assert event.persona == "test_persona"
        assert event.timestamp == datetime(2026, 6, 13, 10, 30, 0)

    @pytest.mark.asyncio
    async def test_on_event_inserts_chat_llm_response(self, recorder, mock_repo):
        """Verify _on_event handles chat.llm_response correctly."""
        data = {
            "session_id": "sess_chat_002",
            "persona": "test_persona",
            "content": "I am a helpful assistant.",
            "timestamp": "2026-06-13T10:30:01",
        }

        await recorder._on_event("chat.llm_response", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.event_type == "chat.llm_response"
        assert event.summary == "🤖 I am a helpful assistant."
        assert event.session_id == "sess_chat_002"

    @pytest.mark.asyncio
    async def test_on_event_inserts_session_compact(self, recorder, mock_repo):
        """Verify _on_event handles session.compact correctly."""
        data = {
            "session_id": "sess_chat_003",
            "persona": "test_persona",
            "before_tokens": 8000,
            "after_tokens": 3000,
            "timestamp": "2026-06-13T10:30:02",
        }

        await recorder._on_event("session.compact", data)

        mock_repo.insert.assert_called_once()
        event: SessionEvent = mock_repo.insert.call_args[0][0]
        assert event.event_type == "session.compact"
        assert event.summary == "📦 Compressed: 8000→3000 tokens"
        assert event.session_id == "sess_chat_003"
