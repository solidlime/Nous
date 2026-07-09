"""Tests for PersonaService with an InMemory repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nous.domain.persona.entities import (
    BodyStateRecord,
    ContextEntry,
    EmotionRecord,
    PersonaState,
)
from nous.domain.persona.service import PersonaService
from nous.domain.shared.result import Result, Success

if TYPE_CHECKING:
    from nous.domain.shared.errors import RepositoryError

# ---------------------------------------------------------------------------
# InMemory PersonaRepository
# ---------------------------------------------------------------------------


class InMemoryPersonaRepository:
    """Protocol-compatible in-memory repo for PersonaService tests."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, str]] = {}
        self._emotions: dict[str, list[EmotionRecord]] = {}
        self._body_state_history: dict[str, list[BodyStateRecord]] = {}
        self._user_info: dict[str, dict[str, str]] = {}
        self._persona_info: dict[str, dict[str, str]] = {}

    def get_current_state(self, persona: str) -> Result[PersonaState, RepositoryError]:
        state_map = self._state.get(persona, {})
        user_info = self._user_info.get(persona, {})
        persona_info = self._persona_info.get(persona, {})
        return Success(
            PersonaState(
                persona=persona,
                emotion=state_map.get("emotion", "neutral"),
                emotion_intensity=float(state_map.get("emotion_intensity", "0.0")),
                physical_state=state_map.get("physical_state"),
                mental_state=state_map.get("mental_state"),
                environment=state_map.get("environment"),
                relationship_status=state_map.get("relationship_status"),
                user_info=user_info,
                persona_info=persona_info,
                appearance=state_map.get("appearance"),
                author_note=state_map.get("author_note"),
                author_note_frequency=state_map.get("author_note_frequency", "always"),
            )
        )

    def update_state(
        self,
        persona: str,
        key: str,
        value: str,
        source: str | None = None,
    ) -> Result[None, RepositoryError]:
        if persona not in self._state:
            self._state[persona] = {}
        self._state[persona][key] = value
        return Success(None)

    def get_state_history(self, persona: str, key: str, limit: int = 20) -> Result[list[ContextEntry], RepositoryError]:
        return Success([])

    def add_emotion_record(self, persona: str, record: EmotionRecord) -> Result[None, RepositoryError]:
        if persona not in self._emotions:
            self._emotions[persona] = []
        self._emotions[persona].append(record)
        return Success(None)

    def get_emotion_history(self, persona: str, limit: int = 20) -> Result[list[EmotionRecord], RepositoryError]:
        records = self._emotions.get(persona, [])
        return Success(records[-limit:])

    def set_user_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]:
        if persona not in self._user_info:
            self._user_info[persona] = {}
        self._user_info[persona][key] = value
        return Success(None)

    def set_persona_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]:
        if persona not in self._persona_info:
            self._persona_info[persona] = {}
        self._persona_info[persona][key] = value
        return Success(None)

    def get_user_info(self, persona: str) -> Result[dict, RepositoryError]:
        return Success(self._user_info.get(persona, {}))

    def get_persona_info(self, persona: str) -> Result[dict, RepositoryError]:
        return Success(self._persona_info.get(persona, {}))

    def sync_goals(self, persona: str, goals: list) -> Result[None, RepositoryError]:
        return Success(None)

    def sync_promises(self, persona: str, promises: list) -> Result[None, RepositoryError]:
        return Success(None)

    def add_body_state_record(
        self,
        persona: str,
        body_state_dict: dict[str, float | None],
        context: str | None = None,
    ) -> Result[None, RepositoryError]:
        if persona not in self._body_state_history:
            self._body_state_history[persona] = []
        from datetime import datetime

        self._body_state_history[persona].append(
            BodyStateRecord(
                persona=persona,
                fatigue=body_state_dict.get("fatigue"),
                warmth=body_state_dict.get("warmth"),
                arousal=body_state_dict.get("arousal"),
                heart_rate=body_state_dict.get("heart_rate"),
                pain=body_state_dict.get("pain"),
                timestamp=datetime.now(),
                context=context,
            )
        )
        return Success(None)

    def get_body_state_history(self, persona: str, limit: int = 20) -> Result[list[BodyStateRecord], RepositoryError]:
        records = self._body_state_history.get(persona, [])
        return Success(records[-limit:])

    def get_body_state_history_by_days(
        self, persona: str, days: int = 7
    ) -> Result[list[BodyStateRecord], RepositoryError]:
        records = self._body_state_history.get(persona, [])
        return Success(records)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PERSONA = "test_persona"


@pytest.fixture
def repo():
    return InMemoryPersonaRepository()


@pytest.fixture
def service(repo):
    return PersonaService(repo)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetContext:
    def test_default_state(self, service: PersonaService):
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.persona == PERSONA
        assert state.emotion == "neutral"
        assert state.emotion_intensity == 0.0

    def test_reflects_updates(self, service: PersonaService):
        service.update_emotion(PERSONA, "joy", 0.8)
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.emotion == "joy"


class TestUpdateEmotion:
    def test_updates_emotion(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_emotion(PERSONA, "joy", 0.8)
        assert result.is_ok
        assert repo._state[PERSONA]["emotion"] == "joy"
        assert repo._state[PERSONA]["emotion_intensity"] == "0.8"

    def test_records_in_history(self, service: PersonaService, repo: InMemoryPersonaRepository):
        service.update_emotion(PERSONA, "sadness", 0.6, context="rain")
        records = repo._emotions[PERSONA]
        assert len(records) == 1
        assert records[0].emotion == "sadness"
        assert records[0].context == "rain"

    def test_clamps_intensity(self, service: PersonaService, repo: InMemoryPersonaRepository):
        service.update_emotion(PERSONA, "anger", 1.5)
        assert repo._state[PERSONA]["emotion_intensity"] == "1.0"

    def test_empty_emotion_normalizes_to_neutral(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_emotion(PERSONA, "", 0.5)
        assert result.is_ok
        assert repo._state[PERSONA]["emotion"] == "neutral"

    def test_records_trigger_key(self, service: PersonaService, repo: InMemoryPersonaRepository):
        """trigger_memory_key and context are stored in emotion history."""
        service.update_emotion(PERSONA, "anger", 0.9, trigger_key="mem_abc", context="argument")
        records = repo._emotions[PERSONA]
        assert len(records) == 1
        assert records[0].trigger_memory_key == "mem_abc"
        assert records[0].context == "argument"


class TestUpdatePhysicalState:
    def test_updates_fields(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_physical_state(PERSONA, fatigue="0.8", warmth="0.6")
        assert result.is_ok
        assert repo._state[PERSONA]["fatigue"] == "0.8"
        assert repo._state[PERSONA]["warmth"] == "0.6"

    def test_ignores_none_values(self, service: PersonaService, repo: InMemoryPersonaRepository):
        service.update_physical_state(PERSONA, fatigue="0.5")
        result = service.update_physical_state(PERSONA, fatigue=None, warmth="0.6")
        assert result.is_ok
        # fatigue should remain "0.5" (None doesn't overwrite)
        assert repo._state[PERSONA]["fatigue"] == "0.5"
        assert repo._state[PERSONA]["warmth"] == "0.6"

    def test_ignores_unknown_keys(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_physical_state(PERSONA, unknown_key="value")
        assert result.is_ok
        assert "unknown_key" not in repo._state.get(PERSONA, {})


class TestUpdateRelationship:
    def test_updates_status(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_relationship(PERSONA, "恋人")
        assert result.is_ok
        assert repo._state[PERSONA]["relationship_status"] == "恋人"

    def test_empty_status_fails(self, service: PersonaService):
        result = service.update_relationship(PERSONA, "")
        assert not result.is_ok


class TestUpdateUserInfo:
    def test_sets_user_info(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_user_info(PERSONA, {"name": "太郎", "age": "25"})
        assert result.is_ok
        assert repo._user_info[PERSONA]["name"] == "太郎"
        assert repo._user_info[PERSONA]["age"] == "25"

    def test_empty_dict_noop(self, service: PersonaService):
        result = service.update_user_info(PERSONA, {})
        assert result.is_ok


class TestUpdatePersonaInfo:
    def test_sets_persona_info(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_persona_info(PERSONA, {"nickname": "ヘルタ"})
        assert result.is_ok
        assert repo._persona_info[PERSONA]["nickname"] == "ヘルタ"

    def test_appearance_propagates_to_state(self, service: PersonaService, repo: InMemoryPersonaRepository):
        """appearance key in persona_info should also update PersonaState.appearance."""
        desc = "銀色の長い髪、赤い瞳、白い研究着"
        result = service.update_persona_info(PERSONA, {"appearance": desc})
        assert result.is_ok
        assert repo._persona_info[PERSONA]["appearance"] == desc
        assert repo._state.get(PERSONA, {}).get("appearance") == desc

    def test_appearance_none_does_not_set_state(self, service: PersonaService, repo: InMemoryPersonaRepository):
        """appearance=None should store in persona_info but not touch state."""
        result = service.update_persona_info(PERSONA, {"appearance": None})
        assert result.is_ok
        assert repo._persona_info[PERSONA].get("appearance") == "None"
        assert "appearance" not in repo._state.get(PERSONA, {})

    def test_get_context_reflects_appearance(self, service: PersonaService):
        """Appearance set via persona_info should be readable via get_context."""
        desc = "短い黒髪、青い眼"
        service.update_persona_info(PERSONA, {"appearance": desc})
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.appearance == desc

    def test_appearance_defaults_to_none(self, service: PersonaService):
        """Fresh persona should have appearance=None."""
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.appearance is None


class TestRecordConversationTime:
    def test_records_time(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.record_conversation_time(PERSONA)
        assert result.is_ok
        assert "last_conversation_time" in repo._state.get(PERSONA, {})


class TestAuthorNote:
    def test_author_note_default_is_none(self, service: PersonaService):
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.author_note is None
        assert state.author_note_frequency == "always"

    def test_author_note_persisted_via_update_state(self, service: PersonaService, repo: InMemoryPersonaRepository):
        result = service.update_state(PERSONA, "author_note", "Remember: you are a helpful assistant.")
        assert result.is_ok
        assert repo._state[PERSONA]["author_note"] == "Remember: you are a helpful assistant."

        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.author_note == "Remember: you are a helpful assistant."

    def test_author_note_frequency_custom(self, service: PersonaService, repo: InMemoryPersonaRepository):
        service.update_state(PERSONA, "author_note_frequency", "on_emotion_change")
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.author_note_frequency == "on_emotion_change"

    def test_author_note_roundtrip_with_empty(self, service: PersonaService):
        service.update_state(PERSONA, "author_note", "test note")
        service.update_state(PERSONA, "author_note", "")
        result = service.get_context(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.author_note == ""
