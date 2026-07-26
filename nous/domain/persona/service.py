from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from nous.domain.persona.body_state import extract_body_metrics
from nous.domain.persona.entities import (
    BodyStateRecord,
    EmotionRecord,
    PersonaState,
)
from nous.domain.shared.errors import DomainError, PersonaValidationError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import generate_memory_key, get_now
from nous.domain.value_objects import normalize_emotion, normalize_importance

if TYPE_CHECKING:
    from datetime import datetime

    from nous.application.event_bus import EventBus
    from nous.domain.memory.service import MemoryService
    from nous.domain.persona.repository import PersonaRepository

_logger = logging.getLogger("nous")


class PersonaService:
    """Domain service for persona state management."""

    def __init__(
        self,
        repo: PersonaRepository,
        event_bus: EventBus | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._repo = repo
        self._event_bus = event_bus
        self._memory_service = memory_service

    def get_context(self, persona: str) -> Result[PersonaState, DomainError]:
        """Get current persona state."""
        return self._repo.get_current_state(persona)

    def _fire_event(self, event_type: str, data: dict) -> None:
        """Fire-and-forget event publication from sync context."""
        if self._event_bus is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_bus.publish(event_type, data))
        except RuntimeError:
            pass

    def update_emotion(
        self,
        persona: str,
        emotion: str,
        intensity: float,
        trigger_key: str | None = None,
        context: str | None = None,
    ) -> Result[None, DomainError]:
        """Update persona emotion and record in history."""
        normalized_name = normalize_emotion(emotion)
        clamped = normalize_importance(float(intensity))

        result = self._repo.update_state(persona, "emotion", normalized_name)
        if not result.is_ok:
            return Failure(result.error)  # type: ignore[union-attr]

        result = self._repo.update_state(persona, "emotion_intensity", str(clamped))
        if not result.is_ok:
            return Failure(result.error)  # type: ignore[union-attr]

        # Record last state update timestamp (for memory auto-snapshot)
        now = get_now()
        self._repo.update_state(persona, "last_state_update", now.isoformat())

        # Record history
        record = EmotionRecord(
            emotion=normalized_name,
            intensity=clamped,
            timestamp=now,
            trigger_memory_key=trigger_key,
            context=context,
        )
        result = self._repo.add_emotion_record(persona, record)
        if result.is_ok:
            self._fire_event(
                "context.emotion_changed",
                {
                    "persona": persona,
                    "emotion": normalized_name,
                    "emotion_intensity": clamped,
                    "trigger_key": trigger_key,
                    "context": context,
                },
            )
            # Propagate emotion to recent memories
            self._propagate_emotion_to_memories(persona, normalized_name, clamped)
        return result

    def update_physical_state(
        self,
        persona: str,
        **states: object,
    ) -> Result[None, DomainError]:
        """Update physical/mental/environmental state fields.

        Accepts: environment, fatigue, warmth, arousal, heart_rate, pain.
        (physical_state, mental_state are persisted via
        memory_service.create_memory instead.)
        Updates only non-None values.
        """
        allowed_keys = {
            "environment",
            "fatigue",
            "warmth",
            "arousal",
            "heart_rate",
            "pain",
        }
        updated_values: dict[str, object] = {}
        for key, value in states.items():
            if key not in allowed_keys:
                continue
            if value is None:
                continue
            result = self._repo.update_state(persona, key, str(value))
            if not result.is_ok:
                return Failure(result.error)
            updated_values[key] = value
        if updated_values:
            self._repo.update_state(persona, "last_state_update", get_now().isoformat())
            self._fire_event(
                "context.body_state_changed",
                {
                    "persona": persona,
                    "states": updated_values,
                },
            )
        return Success(None)

    def update_relationship(self, persona: str, status: str) -> Result[None, DomainError]:
        """Update relationship status."""
        if not status or not status.strip():
            return Failure(PersonaValidationError("Relationship status must not be empty"))
        return self._repo.update_state(persona, "relationship_status", status.strip())

    def update_user_info(self, persona: str, user_info: dict) -> Result[None, DomainError]:
        """Merge updates into user info."""
        if not user_info:
            return Success(None)
        for key, value in user_info.items():
            result = self._repo.set_user_info(persona, str(key), str(value))
            if not result.is_ok:
                return Failure(result.error)
        return Success(None)

    def update_persona_info(self, persona: str, persona_info: dict) -> Result[None, DomainError]:
        """Merge updates into persona info.

        If persona_info contains 'goals' key, extracts goals and persists
        them as tagged memories via memory_service (best-effort).
        """
        if not persona_info:
            return Success(None)

        # Extract goals for memory persistence (must happen before skip loop)
        goals_raw = persona_info.get("goals") or persona_info.get("current_goals")
        if goals_raw is not None and self._memory_service is not None:
            self._extract_goals(goals_raw)

        # goals/promises は memory タグで管理するため persona_info には保存しない
        skip_keys = {"goals", "promises", "active_promises", "current_goals"}
        for key, value in persona_info.items():
            if key in skip_keys:
                continue
            serialized = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
            result = self._repo.set_persona_info(persona, str(key), serialized)
            if not result.is_ok:
                return Failure(result.error)
            # appearance は PersonaState の専用フィールドにも反映
            if key == "appearance" and value is not None:
                self._repo.update_state(persona, "appearance", str(value))
        return Success(None)

    def _extract_goals(self, goals_raw: object) -> None:
        """Extract goals from persona_info and persist as tagged memories.

        Best-effort: failures are silently swallowed.
        """
        if self._memory_service is None:
            return

        # Normalize to list of strings
        if isinstance(goals_raw, str):
            try:
                goals_list = json.loads(goals_raw)
                if isinstance(goals_list, str):
                    goals_list = [goals_list]
            except Exception:
                goals_list = [goals_raw] if goals_raw else []
        elif isinstance(goals_raw, list):
            goals_list = [g for g in goals_raw if g]
        else:
            goals_list = []

        if not goals_list:
            return

        # Get existing active goals for duplicate avoidance
        try:
            existing = self._memory_service.get_by_tags(["goal", "active"])
            existing_contents = [m.content for m in (existing.value or [])]
        except Exception:
            existing_contents = []

        for goal_text in goals_list:
            if not goal_text or not isinstance(goal_text, str):
                continue
            if goal_text in existing_contents:
                continue
            try:
                from nous.domain.memory.entities import Memory as _Memory

                now = get_now()
                mem = _Memory(
                    key=generate_memory_key(),
                    content=goal_text,
                    created_at=now,
                    updated_at=now,
                    tags=["goal", "active"],
                    importance=0.8,
                    emotion="anticipation",
                )
                self._memory_service.save_memory(mem)
            except Exception:
                continue

    def get_emotion_history(self, persona: str, limit: int = 20) -> Result[list[EmotionRecord], DomainError]:
        """Get recent emotion change history."""
        return self._repo.get_emotion_history(persona, limit)

    def record_body_state(
        self,
        persona: str,
        body_state_dict: dict[str, float | None],
        context: str | None = None,
    ) -> Result[None, DomainError]:
        """Record body state snapshot into history."""
        return self._repo.add_body_state_record(persona, body_state_dict, context)

    def get_body_state_history(self, persona: str, limit: int = 20) -> Result[list[BodyStateRecord], DomainError]:
        """Get recent body state history (latest first)."""
        return self._repo.get_body_state_history(persona, limit)

    def get_body_state_history_by_days(self, persona: str, days: int = 7) -> Result[list[BodyStateRecord], DomainError]:
        """Get body state history for last N days (oldest first)."""
        return self._repo.get_body_state_history_by_days(persona, days)

    def update_state(self, persona: str, key: str, value: str) -> Result[None, DomainError]:
        """Update an arbitrary persona state key-value pair.

        Low-level access for fields not covered by dedicated methods
        (e.g. author_note, author_note_frequency).
        """
        return self._repo.update_state(persona, key, value)

    def record_conversation_time(self, persona: str) -> Result[None, DomainError]:
        """Record current time as last conversation time."""
        now = get_now()
        return self._repo.update_state(persona, "last_conversation_time", now.isoformat())

    def _propagate_emotion_to_memories(
        self,
        persona: str,
        emotion: str,
        intensity: float,
        recent_minutes: int = 30,
    ) -> None:
        """Update emotion field on memories created/accessed recently.

        Best-effort: failures are silently swallowed.
        """
        if self._memory_service is None:
            return

        now = get_now()
        cutoff = now - timedelta(minutes=recent_minutes)

        try:
            recent = self._memory_service.get_recent(limit=20)
            if not recent.is_ok or not recent.value:
                return

            for mem in recent.value:
                if not mem.created_at or mem.created_at < cutoff:
                    continue
                self._memory_service.update_memory(
                    mem.key,
                    emotion=emotion,
                    emotion_intensity=intensity,
                )
        except Exception:
            _logger.warning("Failed to propagate emotion to memories", exc_info=True)

    @staticmethod
    def build_body_state_dict(state: PersonaState) -> dict[str, float | None]:
        """Extract body state numeric values from a PersonaState as a dict.

        Returns None for values that are None (never set).
        Delegates to extract_body_metrics for shared implementation.
        """
        return extract_body_metrics(state)

    def get_state_snapshot(self, persona: str) -> tuple[str, float, dict[str, float] | None, datetime | None]:
        """Get (emotion_name, emotion_intensity, body_state, snapped_at) for memory auto-snapshot.

        Returns:
            emotion: str (e.g. "joy", "neutral")
            emotion_intensity: float (0.0-1.0)
            body_state: 5-dim dict or None if never set
            snapped_at: timestamp of last state update or None
        """
        state_result = self.get_context(persona)
        if not state_result.is_ok:
            return "neutral", 0.0, None, None
        state = state_result.value  # type: ignore[union-attr]

        emotion = state.emotion or "neutral"
        intensity = state.emotion_intensity or 0.0

        body_state_raw = self.build_body_state_dict(state)
        body_state: dict[str, float] | None = None
        if body_state_raw:
            numeric = {k: v for k, v in body_state_raw.items() if v is not None}
            if numeric:
                body_state = numeric

        return emotion, intensity, body_state, state.last_state_update
