"""Tests for body_state_history table and related functionality."""

from __future__ import annotations

from datetime import timedelta

import pytest

from nous.domain.persona.body_decay import _extract_body_dict
from nous.domain.persona.entities import BodyStateRecord, PersonaState
from nous.domain.persona.service import PersonaService
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository

PERSONA = "test_persona"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_conn(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture
def repo(sqlite_conn):
    return SQLitePersonaRepository(sqlite_conn)


@pytest.fixture
def state():
    return PersonaState(
        persona=PERSONA,
        fatigue=0.8,
        warmth=0.7,
        arousal=0.6,
        heart_rate=0.5,
        pain=0.0,
    )


# ---------------------------------------------------------------------------
# Table schema tests
# ---------------------------------------------------------------------------


class TestBodyStateTableSchema:
    """Verify the body_state_history table exists and has correct columns."""

    def test_table_exists(self, sqlite_conn):
        rows = (
            sqlite_conn.get_memory_db()
            .execute("SELECT name FROM sqlite_master WHERE type='table' AND name='body_state_history'")
            .fetchall()
        )
        assert len(rows) == 1

    def test_index_exists(self, sqlite_conn):
        rows = (
            sqlite_conn.get_memory_db()
            .execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_body_state_history_persona'")
            .fetchall()
        )
        assert len(rows) == 1

    def test_columns(self, sqlite_conn):
        cols = {
            r["name"]: r["type"]
            for r in sqlite_conn.get_memory_db().execute("PRAGMA table_info(body_state_history)").fetchall()
        }
        assert "persona_id" in cols
        assert "fatigue" in cols
        assert "warmth" in cols
        assert "arousal" in cols
        assert "heart_rate" in cols
        assert "pain" in cols
        assert "timestamp" in cols
        assert "context" in cols


# ---------------------------------------------------------------------------
# Repository method tests
# ---------------------------------------------------------------------------


class TestAddBodyStateRecord:
    def test_adds_record(self, repo):
        body_dict = {"fatigue": 0.8, "warmth": 0.7, "arousal": 0.6, "heart_rate": 0.5, "pain": 0.1}
        result = repo.add_body_state_record(PERSONA, body_dict, context="test_record")
        assert result.is_ok

        history = repo.get_body_state_history(PERSONA)
        assert history.is_ok
        records = history.unwrap()
        assert len(records) == 1
        assert records[0].fatigue == pytest.approx(0.8, abs=0.01)
        assert records[0].warmth == pytest.approx(0.7, abs=0.01)
        assert records[0].context == "test_record"

    def test_adds_with_partial_fields(self, repo):
        body_dict = {"fatigue": 0.5, "pain": 0.2}
        result = repo.add_body_state_record(PERSONA, body_dict, context="partial")
        assert result.is_ok

        records = repo.get_body_state_history(PERSONA).unwrap()
        assert len(records) == 1
        assert records[0].fatigue == pytest.approx(0.5, abs=0.01)
        assert records[0].warmth is None  # not provided

    def test_adds_with_empty_dict(self, repo):
        result = repo.add_body_state_record(PERSONA, {}, context="empty")
        assert result.is_ok

        records = repo.get_body_state_history(PERSONA).unwrap()
        assert len(records) == 1
        assert records[0].fatigue is None


class TestGetBodyStateHistory:
    def test_returns_empty_when_no_records(self, repo):
        result = repo.get_body_state_history(PERSONA)
        assert result.is_ok
        assert result.unwrap() == []

    def test_returns_most_recent_first(self, repo):
        # Use explicit DB timestamps to ensure ordering
        db = repo._db
        db.execute(
            "INSERT INTO body_state_history (persona_id, fatigue, timestamp, context) VALUES (?,?,?,?)",
            (PERSONA, 0.8, "2025-01-01T00:00:00", "first"),
        )
        db.execute(
            "INSERT INTO body_state_history (persona_id, fatigue, timestamp, context) VALUES (?,?,?,?)",
            (PERSONA, 0.8, "2025-01-02T00:00:00", "second"),
        )
        db.commit()

        records = repo.get_body_state_history(PERSONA).unwrap()
        assert len(records) == 2
        # Most recent first
        assert records[0].context == "second"
        assert records[1].context == "first"

    def test_respects_limit(self, repo):
        body_dict = {"fatigue": 0.5}
        for i in range(5):
            repo.add_body_state_record(PERSONA, body_dict, context=f"rec_{i}")

        records = repo.get_body_state_history(PERSONA, limit=3).unwrap()
        assert len(records) == 3


class TestGetBodyStateHistoryByDays:
    def test_returns_empty_when_no_records(self, repo):
        result = repo.get_body_state_history_by_days(PERSONA, days=7)
        assert result.is_ok
        assert result.unwrap() == []

    def test_returns_recent_records(self, repo):
        body_dict = {"fatigue": 0.5}
        repo.add_body_state_record(PERSONA, body_dict, context="recent")

        records = repo.get_body_state_history_by_days(PERSONA, days=7).unwrap()
        assert len(records) == 1

    def test_ascending_order(self, repo):
        from datetime import timedelta

        from nous.domain.shared.time_utils import get_now

        now = get_now()
        db = repo._db
        t1 = (now - timedelta(hours=5)).isoformat()
        t2 = (now - timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO body_state_history (persona_id, fatigue, timestamp, context) VALUES (?,?,?,?)",
            (PERSONA, 0.5, t1, "first"),
        )
        db.execute(
            "INSERT INTO body_state_history (persona_id, fatigue, timestamp, context) VALUES (?,?,?,?)",
            (PERSONA, 0.5, t2, "second"),
        )
        db.commit()

        records = repo.get_body_state_history_by_days(PERSONA, days=7).unwrap()
        assert len(records) == 2
        # Ascending: oldest first
        assert records[0].context == "first"
        assert records[1].context == "second"


# ---------------------------------------------------------------------------
# _extract_body_dict tests
# ---------------------------------------------------------------------------


class TestExtractBodyDict:
    def test_extracts_all_fields(self, state):
        result = _extract_body_dict(state)
        assert result["fatigue"] == 0.8
        assert result["warmth"] == 0.7
        assert result["arousal"] == 0.6
        assert result["heart_rate"] == 0.5
        assert result["pain"] == 0.0

    def test_handles_none_fields(self):
        empty = PersonaState(persona=PERSONA)
        result = _extract_body_dict(empty)
        assert all(v is None for v in result.values())


# ---------------------------------------------------------------------------
# Service layer tests (via InMemory repo)
# ---------------------------------------------------------------------------


class TestServiceBodyStateHistory:
    def test_record_body_state(self, repo):
        service = PersonaService(repo)
        body_dict = {"fatigue": 0.7, "warmth": 0.6}
        result = service.record_body_state(PERSONA, body_dict, context="test")
        assert result.is_ok

        records = service.get_body_state_history(PERSONA).unwrap()
        assert len(records) == 1
        assert records[0].fatigue == pytest.approx(0.7, abs=0.01)

    def test_get_body_state_history_by_days(self, repo):
        service = PersonaService(repo)
        service.record_body_state(PERSONA, {"fatigue": 0.8}, context="test")

        records = service.get_body_state_history_by_days(PERSONA, days=7).unwrap()
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Integration: body_decay records history
# ---------------------------------------------------------------------------


class TestBodyDecayRecordsHistory:
    """Verify that apply_body_decay_if_needed records body state before and after."""

    @pytest.mark.asyncio
    async def test_records_before_and_after_state(self, sqlite_conn):
        """Apply body decay and verify before/after records exist."""
        repo = SQLitePersonaRepository(sqlite_conn)
        service = PersonaService(repo)

        # Set up initial body state
        service.update_physical_state(PERSONA, fatigue="0.9", warmth="0.8", arousal="0.7")

        # Set last_conversation_time far in the past to trigger decay
        past = get_now() - timedelta(hours=24)
        repo.update_state(PERSONA, "last_conversation_time", past.isoformat())

        # Re-read state and apply decay
        state_result = service.get_context(PERSONA)
        assert state_result.is_ok
        state = state_result.unwrap()

        # Manually trigger the decay logic inline (same as apply_body_decay_if_needed)
        from nous.domain.persona.body_decay import apply_body_decay_if_needed

        changed = await apply_body_decay_if_needed(service, PERSONA, state)

        # Body decay should detect changes (24h elapsed)
        assert changed, "Expected body decay to detect changes with 24h gap"

        # Check body state history has before/after records
        records = repo.get_body_state_history(PERSONA).unwrap()
        assert len(records) >= 2

        contexts = [r.context for r in records]
        assert "before_body_decay" in contexts
        assert "after_body_decay" in contexts

        # Before state should have original high values
        before = [r for r in records if r.context == "before_body_decay"][0]
        assert before.fatigue == pytest.approx(0.9, abs=0.01)

        # After state should have decayed values
        after = [r for r in records if r.context == "after_body_decay"][0]
        assert after.fatigue is not None
        assert after.fatigue < 0.9  # fatigue should have decayed toward 0

    @pytest.mark.asyncio
    async def test_no_records_when_no_decay_needed(self, sqlite_conn):
        """No records should be created when body decay doesn't change anything."""
        repo = SQLitePersonaRepository(sqlite_conn)
        service = PersonaService(repo)

        state = PersonaState(persona=PERSONA)

        from nous.domain.persona.body_decay import apply_body_decay_if_needed

        changed = await apply_body_decay_if_needed(service, PERSONA, state)
        assert not changed

        records = repo.get_body_state_history(PERSONA).unwrap()
        assert len(records) == 0


# ---------------------------------------------------------------------------
# _format_lightweight_response with body_state_history
# ---------------------------------------------------------------------------


class TestBodyStateHistoryInContext:
    def test_body_state_history_included_in_output(self):
        """Verify body_state_history is rendered in _format_lightweight_response when >= 2 records."""
        from nous.api.mcp._tools_helpers import _format_lightweight_response

        state = PersonaState(persona=PERSONA, fatigue=0.5, warmth=0.5)
        history = [
            BodyStateRecord(
                fatigue=0.8, warmth=0.7, context="before_body_decay", timestamp=get_now() - timedelta(hours=24)
            ),
            BodyStateRecord(fatigue=0.5, warmth=0.5, context="after_body_decay", timestamp=get_now()),
        ]
        result = _format_lightweight_response(
            state=state,
            top_memories=[],
            goals=[],
            promises=[],
            equipment={},
            recent=[],
            body_state_history=history,
        )
        assert "Body state history:" in result
        assert "fatigue:80%" in result
        assert "after_body_decay" in result

    def test_body_state_history_skipped_when_single_record(self):
        """Only 1 record → don't show body state history section."""
        from nous.api.mcp._tools_helpers import _format_lightweight_response

        state = PersonaState(persona=PERSONA, fatigue=0.5)
        history = [
            BodyStateRecord(fatigue=0.8, context="before_body_decay", timestamp=get_now()),
        ]
        result = _format_lightweight_response(
            state=state,
            top_memories=[],
            goals=[],
            promises=[],
            equipment={},
            recent=[],
            body_state_history=history,
        )
        assert "Body state history:" not in result

    def test_body_state_history_skipped_when_none(self):
        """None history → don't show body state history section."""
        from nous.api.mcp._tools_helpers import _format_lightweight_response

        state = PersonaState(persona=PERSONA, fatigue=0.5)
        result = _format_lightweight_response(
            state=state,
            top_memories=[],
            goals=[],
            promises=[],
            equipment={},
            recent=[],
            body_state_history=None,
        )
        assert "Body state history:" not in result
