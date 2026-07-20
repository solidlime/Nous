"""Additional tests for SQLitePersonaRepository — covering uncovered paths."""

from __future__ import annotations

import pytest

from nous.domain.persona.entities import EmotionRecord
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.persona_repo import (
    SQLitePersonaRepository,
    _parse_or_none,
    _safe_float,
)

PERSONA = "test_persona"


@pytest.fixture
def persona_repo(sqlite_conn):
    return SQLitePersonaRepository(sqlite_conn)


class TestSafeFloat:
    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_valid_float_string(self):
        assert _safe_float("0.5") == 0.5

    def test_invalid_string_returns_none(self):
        assert _safe_float("not_a_number") is None

    def test_integer_string(self):
        assert _safe_float("1") == 1.0


class TestParseOrNone:
    def test_none_returns_none(self):
        assert _parse_or_none(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_or_none("") is None

    def test_valid_iso_string(self):
        result = _parse_or_none("2025-01-01T00:00:00+09:00")
        assert result is not None
        assert result.year == 2025

    def test_invalid_string_returns_none(self):
        assert _parse_or_none("not-a-date") is None


class TestGetEmotionHistoryByDays:
    def test_returns_empty_when_no_records(self, persona_repo):
        result = persona_repo.get_emotion_history_by_days(PERSONA, days=7)
        assert result.is_ok
        assert result.unwrap() == []

    def test_returns_recent_emotions(self, persona_repo):
        record = EmotionRecord(emotion="joy", intensity=0.8, timestamp=get_now())
        persona_repo.add_emotion_record(PERSONA, record)

        result = persona_repo.get_emotion_history_by_days(PERSONA, days=7)
        assert result.is_ok
        assert len(result.unwrap()) == 1
        assert result.unwrap()[0].emotion == "joy"

    def test_ascending_order(self, persona_repo):
        from datetime import timedelta

        t1 = get_now() - timedelta(hours=5)
        t2 = get_now() - timedelta(hours=1)
        persona_repo.add_emotion_record(PERSONA, EmotionRecord(emotion="sadness", intensity=0.5, timestamp=t2))
        persona_repo.add_emotion_record(PERSONA, EmotionRecord(emotion="joy", intensity=0.9, timestamp=t1))

        result = persona_repo.get_emotion_history_by_days(PERSONA, days=1)
        assert result.is_ok
        records = result.unwrap()
        assert len(records) == 2
        # Ascending order: oldest first
        assert records[0].emotion == "joy"
        assert records[1].emotion == "sadness"


class TestAppearanceField:
    def test_appearance_read_from_state_map(self, persona_repo):
        """appearance stored in context_state should be reflected in PersonaState."""
        persona_repo.update_state(PERSONA, "appearance", "銀色の長い髪、赤い瞳")
        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        assert result.unwrap().appearance == "銀色の長い髪、赤い瞳"

    def test_appearance_defaults_to_none(self, persona_repo):
        """Fresh persona with no appearance set should have None."""
        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        assert result.unwrap().appearance is None


class TestGetCurrentStateWithBodyFields:
    def test_fatigue_and_warmth_in_state(self, persona_repo):
        persona_repo.update_state(PERSONA, "fatigue", "0.7")
        persona_repo.update_state(PERSONA, "warmth", "0.8")
        persona_repo.update_state(PERSONA, "arousal", "0.5")

        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.fatigue == pytest.approx(0.7, abs=0.01)
        assert state.warmth == pytest.approx(0.8, abs=0.01)
        assert state.arousal == pytest.approx(0.5, abs=0.01)

    def test_last_conversation_time_from_memories(self, persona_repo, sqlite_conn):
        """last_conversation_time is derived from memories table when available."""
        now = "2025-06-01T12:00:00+09:00"
        sqlite_conn.get_memory_db().execute(
            "INSERT INTO memories (key, content, created_at, updated_at) VALUES (?,?,?,?)",
            ("mem_test", "test", now, now),
        )
        sqlite_conn.get_memory_db().commit()

        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        # last_conversation_time should not be None since memories exist
        assert result.unwrap().last_conversation_time is not None
