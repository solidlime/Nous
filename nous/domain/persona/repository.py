from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nous.domain.persona.entities import (
        BodyStateRecord,
        EmotionRecord,
        PersonaState,
    )
    from nous.domain.shared.errors import RepositoryError
    from nous.domain.shared.result import Result


@runtime_checkable
class PersonaRepository(Protocol):
    """Protocol interface for persona data storage.

    All persona persistence backends must implement these methods.
    """

    # ------------------------------------------------------------------
    # Persona state
    # ------------------------------------------------------------------

    def get_current_state(self, persona: str) -> Result[PersonaState, RepositoryError]: ...

    def update_state(
        self,
        persona: str,
        key: str,
        value: str,
        source: str | None = None,
    ) -> Result[None, RepositoryError]: ...

    # ------------------------------------------------------------------
    # Emotion history
    # ------------------------------------------------------------------

    def add_emotion_record(self, persona: str, record: EmotionRecord) -> Result[None, RepositoryError]: ...

    def get_emotion_history(self, persona: str, limit: int = 20) -> Result[list[EmotionRecord], RepositoryError]: ...

    # ------------------------------------------------------------------
    # Body state history
    # ------------------------------------------------------------------

    def add_body_state_record(
        self,
        persona: str,
        body_state_dict: dict[str, float | None],
        context: str | None = None,
    ) -> Result[None, RepositoryError]: ...

    def get_body_state_history(
        self, persona: str, limit: int = 20
    ) -> Result[list[BodyStateRecord], RepositoryError]: ...

    # ------------------------------------------------------------------
    # User / Persona info
    # ------------------------------------------------------------------

    def set_user_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]: ...

    def set_persona_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]: ...
