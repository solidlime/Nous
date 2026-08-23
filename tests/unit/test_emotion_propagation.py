"""Tests for emotion propagation from persona changes to memories."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.persona.service import PersonaService
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from nous.domain.persona.entities import EmotionRecord

PERSONA = "test_persona"

# ---------------------------------------------------------------------------
# Fake MemoryService (records update_memory calls)
# ---------------------------------------------------------------------------


class FakeMemoryService:
    """Minimal MemoryService stub for propagation tests."""

    def __init__(self) -> None:
        self.memories: list[Memory] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []

    def get_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]:
        return Success(self.memories[:limit])

    def update_memory(self, key: str, **updates: Any) -> Result[Memory, RepositoryError]:
        self.updated.append((key, updates))
        now = get_now()
        return Success(
            Memory(
                key=key,
                content="",
                created_at=now,
                updated_at=now,
            )
        )


# ---------------------------------------------------------------------------
# InMemory PersonaRepository (minimal for update_emotion)
# ---------------------------------------------------------------------------


class InMemoryPersonaRepository:
    """Minimal in-memory repo for PersonaService.update_emotion tests."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, str]] = {}
        self._emotions: dict[str, list[EmotionRecord]] = {}

    def get_current_state(self, persona: str) -> Result[Any, RepositoryError]:
        return Success(None)

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

    def add_emotion_record(self, persona: str, record: EmotionRecord) -> Result[None, RepositoryError]:
        if persona not in self._emotions:
            self._emotions[persona] = []
        self._emotions[persona].append(record)
        return Success(None)

    def get_emotion_history(self, persona: str, limit: int = 20) -> Result[list[EmotionRecord], RepositoryError]:
        return Success([])

    def get_state_history(self, persona: str, key: str, limit: int = 20) -> Result[list[Any], RepositoryError]:
        return Success([])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo() -> InMemoryPersonaRepository:
    return InMemoryPersonaRepository()


@pytest.fixture
def mem_service() -> FakeMemoryService:
    return FakeMemoryService()


@pytest.fixture
def service(repo: InMemoryPersonaRepository, mem_service: FakeMemoryService) -> PersonaService:
    return PersonaService(repo, memory_service=mem_service)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmotionPropagation:
    def test_propagates_to_recent_memory(
        self,
        service: PersonaService,
        mem_service: FakeMemoryService,
    ):
        """Memory created within propagation window gets emotion update."""
        now = get_now()
        mem_service.memories = [
            Memory(
                key="mem_recent",
                content="I just talked about my day",
                created_at=now - timedelta(minutes=5),
                updated_at=now - timedelta(minutes=5),
            )
        ]

        service.update_emotion(PERSONA, "joy", 0.8)

        assert len(mem_service.updated) == 1
        key, updates = mem_service.updated[0]
        assert key == "mem_recent"
        assert updates["emotion"] == "joy"
        assert updates["emotion_intensity"] == 0.8

    def test_skips_old_memories(
        self,
        service: PersonaService,
        mem_service: FakeMemoryService,
    ):
        """Memories older than propagation window are not updated."""
        now = get_now()
        old = Memory(
            key="mem_old",
            content="old memory",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        )
        recent = Memory(
            key="mem_recent",
            content="recent memory",
            created_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=5),
        )
        mem_service.memories = [old, recent]

        service.update_emotion(PERSONA, "sadness", 0.6)

        # Only recent memory should be updated
        assert len(mem_service.updated) == 1
        key, _ = mem_service.updated[0]
        assert key == "mem_recent"

    def test_no_memory_no_error(
        self,
        service: PersonaService,
        mem_service: FakeMemoryService,
    ):
        """No recent memories → no error, propagation skipped."""
        mem_service.memories = []

        result = service.update_emotion(PERSONA, "joy", 0.8)
        assert result.is_ok
        assert len(mem_service.updated) == 0

    def test_no_memory_service_no_error(
        self,
        repo: InMemoryPersonaRepository,
    ):
        """memory_service=None → propagation silently skipped."""
        svc = PersonaService(repo, memory_service=None)
        result = svc.update_emotion(PERSONA, "joy", 0.8)
        assert result.is_ok

    def test_failure_does_not_propagate(
        self,
        service: PersonaService,
        mem_service: FakeMemoryService,
    ):
        """update_memory failure is silently swallowed."""
        now = get_now()
        mem_service.memories = [
            Memory(
                key="mem_bad",
                content="problematic",
                created_at=now - timedelta(minutes=1),
                updated_at=now - timedelta(minutes=1),
            )
        ]

        # Replace update_memory to simulate failure
        def failing_update(key: str, **updates: Any) -> Failure:
            return Failure(RepositoryError("fail"))

        mem_service.update_memory = failing_update  # type: ignore[assignment]

        # Must not raise
        result = service.update_emotion(PERSONA, "anger", 0.9)
        assert result.is_ok
