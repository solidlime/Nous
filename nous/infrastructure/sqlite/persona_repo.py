from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.persona.entities import (
    BodyStateRecord,
    ContextEntry,
    EmotionRecord,
    PersonaState,
)
from nous.domain.persona.repository import PersonaRepository
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now, parse_iso
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection

logger = get_logger(__name__)


class SQLitePersonaRepository(PersonaRepository):
    """SQLite-backed implementation of the PersonaRepository interface."""

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return self._conn.get_memory_db()

    # ------------------------------------------------------------------
    # Persona state (bi-temporal)
    # ------------------------------------------------------------------

    def get_current_state(self, persona: str) -> Result[PersonaState, RepositoryError]:
        """Build the current persona state from context_state, user_info, persona_info."""
        try:
            # Get current context values (valid_until IS NULL means "current")
            rows = self._db.execute(
                """
                SELECT key, value FROM context_state
                WHERE persona = ? AND valid_until IS NULL
                """,
                (persona,),
            ).fetchall()
            state_map: dict[str, str] = {row["key"]: row["value"] for row in rows}

            # Get user_info
            user_rows = self._db.execute(
                "SELECT key, value FROM user_info WHERE persona = ?",
                (persona,),
            ).fetchall()
            user_info = {row["key"]: row["value"] for row in user_rows}

            # Get persona_info
            persona_rows = self._db.execute(
                "SELECT key, value FROM persona_info WHERE persona = ?",
                (persona,),
            ).fetchall()
            persona_info = {}
            for row in persona_rows:
                try:
                    persona_info[row["key"]] = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    persona_info[row["key"]] = row["value"]

            return Success(
                PersonaState(
                    persona=persona,
                    emotion=state_map.get("emotion", "neutral"),
                    emotion_intensity=float(state_map.get("emotion_intensity", "0.0")),
                    physical_state=state_map.get("physical_state"),
                    mental_state=state_map.get("mental_state"),
                    environment=state_map.get("environment"),
                    relationship_status=state_map.get("relationship_status"),
                    fatigue=_safe_float(state_map.get("fatigue")),
                    warmth=_safe_float(state_map.get("warmth")),
                    arousal=_safe_float(state_map.get("arousal")),
                    heart_rate=_safe_float(state_map.get("heart_rate")),
                    pain=_safe_float(state_map.get("pain")),
                    speech_style=state_map.get("speech_style"),
                    user_info=user_info,
                    persona_info=persona_info,
                    last_conversation_time=_resolve_last_conversation_time(self._db, state_map),
                    last_state_update=_parse_or_none(state_map.get("last_state_update")),
                    author_note=state_map.get("author_note"),
                    author_note_frequency=state_map.get("author_note_frequency", "always"),
                )
            )
        except Exception as e:
            logger.error("Failed to get persona state for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    def update_state(
        self,
        persona: str,
        key: str,
        value: str,
        source: str | None = None,
    ) -> Result[None, RepositoryError]:
        """Update a single state key using bi-temporal pattern.

        1. Close the current record (set valid_until = now)
        2. Insert a new record with valid_from = now
        """
        try:
            now = format_iso(get_now())
            # Close current record
            self._db.execute(
                """
                UPDATE context_state
                SET valid_until = ?
                WHERE persona = ? AND key = ? AND valid_until IS NULL
                """,
                (now, persona, key),
            )
            # Insert new record
            self._db.execute(
                """
                INSERT INTO context_state (persona, key, value, valid_from, change_source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (persona, key, value, now, source),
            )
            self._db.commit()
            logger.info("State updated: persona=%s key=%s", persona, key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to update state %s/%s: %s", persona, key, e)
            return Failure(RepositoryError(str(e)))

    def get_state_history(self, persona: str, key: str, limit: int = 20) -> Result[list[ContextEntry], RepositoryError]:
        """Get the change history for a specific state key."""
        try:
            rows = self._db.execute(
                """
                SELECT * FROM context_state
                WHERE persona = ? AND key = ?
                ORDER BY valid_from DESC
                LIMIT ?
                """,
                (persona, key, limit),
            ).fetchall()
            return Success([self._row_to_context_entry(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get state history %s/%s: %s", persona, key, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Emotion history
    # ------------------------------------------------------------------

    def add_emotion_record(self, persona: str, record: EmotionRecord) -> Result[None, RepositoryError]:
        """Add an emotion record to history."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO emotion_history
                    (emotion_type, intensity, timestamp, trigger_memory_key, context)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.emotion,
                    record.intensity,
                    format_iso(record.timestamp) if record.timestamp else now,
                    record.trigger_memory_key,
                    record.context,
                ),
            )
            self._db.commit()
            logger.info("Emotion record added: %s (%.1f)", record.emotion, record.intensity)
            return Success(None)
        except Exception as e:
            logger.error("Failed to add emotion record: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_emotion_history(self, persona: str, limit: int = 20) -> Result[list[EmotionRecord], RepositoryError]:
        """Get recent emotion history."""
        try:
            rows = self._db.execute(
                """
                SELECT * FROM emotion_history
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return Success([self._row_to_emotion_record(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get emotion history: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_emotion_history_by_days(self, persona: str, days: int = 7) -> Result[list[EmotionRecord], RepositoryError]:
        """Get emotion history for the last N days, ordered by timestamp ascending."""
        try:
            from datetime import timedelta

            cutoff = get_now() - timedelta(days=days)
            rows = self._db.execute(
                """
                SELECT * FROM emotion_history
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (cutoff.isoformat(),),
            ).fetchall()
            return Success([self._row_to_emotion_record(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get emotion history by days: %s", e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Body state history
    # ------------------------------------------------------------------

    def add_body_state_record(
        self,
        persona: str,
        body_state_dict: dict[str, float | None],
        context: str | None = None,
    ) -> Result[None, RepositoryError]:
        """Insert a body state record into history."""
        try:
            self._db.execute(
                """
                INSERT INTO body_state_history
                    (persona_id, fatigue, warmth, arousal, heart_rate, pain, context)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persona,
                    body_state_dict.get("fatigue"),
                    body_state_dict.get("warmth"),
                    body_state_dict.get("arousal"),
                    body_state_dict.get("heart_rate"),
                    body_state_dict.get("pain"),
                    context,
                ),
            )
            self._db.commit()
            return Success(None)
        except Exception as e:
            logger.error("Failed to add body state record for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    def get_body_state_history(self, persona: str, limit: int = 20) -> Result[list[BodyStateRecord], RepositoryError]:
        """Get recent body state history records (latest first)."""
        try:
            rows = self._db.execute(
                """
                SELECT * FROM body_state_history
                WHERE persona_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (persona, limit),
            ).fetchall()
            return Success([self._row_to_body_state_record(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get body state history for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    def get_body_state_history_by_days(
        self, persona: str, days: int = 7
    ) -> Result[list[BodyStateRecord], RepositoryError]:
        """Get body state history for the last N days, ordered by timestamp ascending."""
        try:
            from datetime import timedelta

            from nous.domain.shared.time_utils import get_now

            cutoff = get_now() - timedelta(days=days)
            rows = self._db.execute(
                """
                SELECT * FROM body_state_history
                WHERE persona_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (persona, cutoff.isoformat()),
            ).fetchall()
            return Success([self._row_to_body_state_record(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get body state history by days for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # User / Persona info (key-value store)
    # ------------------------------------------------------------------

    def set_user_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]:
        """Set a user info key-value pair (upsert)."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT OR REPLACE INTO user_info (persona, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (persona, key, value, now),
            )
            self._db.commit()
            return Success(None)
        except Exception as e:
            logger.error("Failed to set user_info %s/%s: %s", persona, key, e)
            return Failure(RepositoryError(str(e)))

    def set_persona_info(self, persona: str, key: str, value: str) -> Result[None, RepositoryError]:
        """Set a persona info key-value pair (upsert)."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT OR REPLACE INTO persona_info (persona, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (persona, key, value, now),
            )
            self._db.commit()
            return Success(None)
        except Exception as e:
            logger.error("Failed to set persona_info %s/%s: %s", persona, key, e)
            return Failure(RepositoryError(str(e)))

    def get_user_info(self, persona: str) -> Result[dict, RepositoryError]:
        """Get all user_info for a persona."""
        try:
            rows = self._db.execute(
                "SELECT key, value FROM user_info WHERE persona = ?",
                (persona,),
            ).fetchall()
            return Success({row["key"]: row["value"] for row in rows})
        except Exception as e:
            logger.error("Failed to get user_info for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    def get_persona_info(self, persona: str) -> Result[dict, RepositoryError]:
        """Get all persona_info for a persona."""
        try:
            rows = self._db.execute(
                "SELECT key, value FROM persona_info WHERE persona = ?",
                (persona,),
            ).fetchall()
            return Success({row["key"]: row["value"] for row in rows})
        except Exception as e:
            logger.error("Failed to get persona_info for '%s': %s", persona, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_context_entry(row) -> ContextEntry:
        return ContextEntry(
            persona=row["persona"],
            key=row["key"],
            value=row["value"],
            valid_from=parse_iso(row["valid_from"]),
            valid_until=_parse_or_none(row["valid_until"]),
            change_source=row["change_source"],
        )

    @staticmethod
    def _row_to_emotion_record(row) -> EmotionRecord:
        return EmotionRecord(
            id=row["id"],
            emotion=row["emotion_type"],
            intensity=row["intensity"] or 0.5,
            timestamp=parse_iso(row["timestamp"]),
            trigger_memory_key=row["trigger_memory_key"],
            context=row["context"],
        )

    @staticmethod
    def _row_to_body_state_record(row) -> BodyStateRecord:
        return BodyStateRecord(
            id=row["id"],
            persona=row["persona_id"],
            fatigue=row["fatigue"],
            warmth=row["warmth"],
            arousal=row["arousal"],
            heart_rate=row["heart_rate"],
            pain=row["pain"],
            timestamp=parse_iso(row["timestamp"]),
            context=row["context"],
        )


def _resolve_last_conversation_time(db, state_map: dict):
    """Derive last conversation time from the most recent memory operation.

    Falls back to the stored context_state value if no memories exist.
    """
    try:
        row = db.execute("SELECT MAX(COALESCE(updated_at, created_at)) AS last_activity FROM memories").fetchone()
        if row and row["last_activity"]:
            memory_time = parse_iso(row["last_activity"])
            stored_time = _parse_or_none(state_map.get("last_conversation_time"))
            candidates = [t for t in (memory_time, stored_time) if t is not None]
            return max(candidates) if candidates else None
    except Exception:
        pass
    return _parse_or_none(state_map.get("last_conversation_time"))


def _safe_float(value: str | None) -> float | None:
    """Safely convert a string to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_or_none(value: str | None):
    """Parse ISO datetime or return None."""
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:
        return None
