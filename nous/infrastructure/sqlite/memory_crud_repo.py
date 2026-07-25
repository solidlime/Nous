from __future__ import annotations

import json
from typing import Any

from nous.domain.memory.entities import Memory
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite._utils import _parse_json_list

logger = get_logger(__name__)


class MemoryCrudMixin:
    """Mixin providing CRUD operations for SQLiteMemoryRepository."""

    @staticmethod
    def _active_where() -> str:
        """Return WHERE clause fragment to exclude tombstoned memories."""
        return "lifecycle_status != 'tombstoned'"

    def save(self, memory: Memory) -> Result[str, RepositoryError]:
        """Persist a Memory entity. Returns the memory key on success."""
        try:
            now = format_iso(get_now())
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                """
                INSERT OR REPLACE INTO memories (
                    key, content, created_at, updated_at, tags, importance,
                    emotion, emotion_intensity, physical_state, mental_state,
                    environment, relationship_status, source_context,
                    related_keys, summary_ref, equipped_items, access_count,
                    last_accessed, privacy_level, body_state, state_snapped_at,
                    lifecycle_status,
                    kind, episodic_time, episodic_place, episodic_people,
                    source_type, confidence, derived_from,
                    valid_from, valid_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.key,
                    memory.content,
                    format_iso(memory.created_at),
                    now,
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.importance,
                    memory.emotion,
                    memory.emotion_intensity,
                    memory.physical_state,
                    memory.mental_state,
                    memory.environment,
                    memory.relationship_status,
                    memory.source_context,
                    json.dumps(memory.related_keys, ensure_ascii=False),
                    memory.summary_ref,
                    memory.equipped_items,
                    memory.access_count,
                    format_iso(memory.last_accessed) if memory.last_accessed else None,
                    memory.privacy_level,
                    json.dumps(memory.body_state, ensure_ascii=False) if memory.body_state else None,
                    format_iso(memory.state_snapped_at) if memory.state_snapped_at else None,
                    memory.lifecycle_status,
                    memory.kind,
                    memory.episodic_time,
                    memory.episodic_place,
                    json.dumps(memory.episodic_people, ensure_ascii=False) if memory.episodic_people else None,
                    memory.source_type,
                    memory.confidence,
                    memory.derived_from,
                    format_iso(memory.valid_from) if memory.valid_from else None,
                    format_iso(memory.valid_until) if memory.valid_until else None,
                ),
            )
            # T4-A: Insert initial memory_strength record so WebUI shows a
            # strength value immediately (before Ebbinghaus decay worker runs).
            # INSERT OR IGNORE preserves any existing record on re-save.
            self._db.execute(
                """
                INSERT OR IGNORE INTO memory_strength (memory_key, strength, stability, recall_count)
                VALUES (?, 1.0, 1.0, 0)
                """,
                (memory.key,),
            )
            self._db.commit()
            logger.info("Memory saved: %s", memory.key)
            return Success(memory.key)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to save memory %s: %s", memory.key, e)
            return Failure(RepositoryError(str(e)))

    def find_by_key(self, key: str) -> Result[Memory | None, RepositoryError]:
        """Find a single memory by its key."""
        row = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
        if row is None:
            return Success(None)
        return Success(self._row_to_memory(row))

    def find_by_content_exact(self, content: str) -> Result[Memory | None, RepositoryError]:
        """Find a memory by exact content match (case-insensitive, excludes tombstoned)."""
        row = self._db.execute(
            f"SELECT * FROM memories WHERE LOWER(content) = LOWER(?) AND {self._active_where()} LIMIT 1",
            (content.strip(),),
        ).fetchone()
        if row is None:
            return Success(None)
        return Success(self._row_to_memory(row))

    def find_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]:
        """Return the most recently updated memories with optional pagination offset."""
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    def find_by_tags(self, tags: list[str], limit: int = 10) -> Result[list[Memory], RepositoryError]:
        """Find memories that contain any of the specified tags."""
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC"
        ).fetchall()
        result: list[Memory] = []
        tag_set = set(tags)
        for row in rows:
            memory_tags = set(_parse_json_list(row["tags"]))
            if memory_tags & tag_set:
                result.append(self._row_to_memory(row))
                if len(result) >= limit:
                    break
        return Success(result)

    def update(self, key: str, **kwargs: Any) -> Result[Memory, RepositoryError]:
        """Update specific fields of a memory."""
        try:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
            if existing is None:
                self._db.rollback()
                return Failure(RepositoryError(f"Memory not found: {key}"))

            updates: dict[str, Any] = {}
            for field, value in kwargs.items():
                if field in ("tags", "related_keys"):
                    updates[field] = json.dumps(value, ensure_ascii=False)
                elif field in ("created_at", "updated_at", "last_accessed") and value is not None:
                    updates[field] = format_iso(value) if not isinstance(value, str) else value
                elif field == "lifecycle_status":
                    updates[field] = str(value)
                else:
                    updates[field] = value
            updates["updated_at"] = format_iso(get_now())

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [key]
            self._db.execute(
                f"UPDATE memories SET {set_clause} WHERE key = ?",  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
                values,
            )

            updated_row = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
            self._db.commit()
            logger.info("Memory updated: %s", key)
            return Success(self._row_to_memory(updated_row))
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to update memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def delete(self, key: str) -> Result[None, RepositoryError]:
        """Delete a memory and its strength record."""
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute("DELETE FROM memory_strength WHERE memory_key = ?", (key,))
            self._db.execute("DELETE FROM memories WHERE key = ?", (key,))
            self._db.commit()
            logger.info("Memory deleted: %s", key)
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to delete memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def count(self) -> Result[int, RepositoryError]:
        """Count total memories."""
        row = self._db.execute(f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()}").fetchone()
        return Success(row["cnt"])

    def find_all(self) -> Result[list[Memory], RepositoryError]:
        """Return all memories."""
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC"
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    def tombstone(self, key: str) -> Result[None, RepositoryError]:
        """Logically delete a memory by setting lifecycle_status to 'tombstoned'."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                "UPDATE memories SET lifecycle_status = 'tombstoned', updated_at = ? WHERE key = ?",
                (now, key),
            )
            logger.info("Memory tombstoned: %s", key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to tombstone memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_dict(value: str | None) -> dict | None:
        """Parse a JSON dict column. Returns None for empty/null."""
        if not value:
            return None
        try:
            raw = json.loads(value)
            return raw if isinstance(raw, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _parse_iso_or_none(value: str | None):
        """Parse ISO datetime string or return None."""
        if not value:
            return None
        from nous.domain.shared.time_utils import parse_iso

        return parse_iso(value)

    def _row_to_memory(self, row) -> Memory:
        """Convert a database row to a Memory entity."""
        row_keys = row.keys() if hasattr(row, "keys") else []
        return Memory(
            key=row["key"],
            content=row["content"],
            created_at=self._parse_iso_or_none(row["created_at"]) or get_now(),
            updated_at=self._parse_iso_or_none(row["updated_at"]) or get_now(),
            importance=row["importance"] or 0.5,
            emotion=row["emotion"] or "neutral",
            emotion_intensity=row["emotion_intensity"] or 0.0,
            tags=_parse_json_list(row["tags"]),
            privacy_level=row["privacy_level"] or "internal",
            physical_state=row["physical_state"],
            mental_state=row["mental_state"],
            environment=row["environment"],
            relationship_status=row["relationship_status"],
            source_context=row["source_context"],
            related_keys=_parse_json_list(row["related_keys"]),
            summary_ref=row["summary_ref"],
            equipped_items=row["equipped_items"],
            access_count=row["access_count"] or 0,
            last_accessed=self._parse_iso_or_none(row["last_accessed"]) if "last_accessed" in row_keys else None,
            body_state=self._parse_json_dict(row["body_state"]) if "body_state" in row_keys else None,
            state_snapped_at=self._parse_iso_or_none(row["state_snapped_at"])
            if "state_snapped_at" in row_keys
            else None,
            lifecycle_status=row["lifecycle_status"] if "lifecycle_status" in row_keys else "active",
            last_consumed_at=self._parse_iso_or_none(row["last_consumed_at"])
            if "last_consumed_at" in row_keys
            else None,
            # kind fields (safe defaults for old rows)
            kind=row["kind"] if "kind" in row_keys else "semantic",
            episodic_time=row["episodic_time"] if "episodic_time" in row_keys else None,
            episodic_place=row["episodic_place"] if "episodic_place" in row_keys else None,
            episodic_people=row["episodic_people"] if "episodic_people" in row_keys else None,
            # source provenance (safe defaults for old rows)
            source_type=row["source_type"] if "source_type" in row_keys else "user_stated",
            confidence=row["confidence"] if "confidence" in row_keys else 1.0,
            derived_from=row["derived_from"] if "derived_from" in row_keys else None,
            # temporal validity (safe defaults for old rows)
            valid_from=self._parse_iso_or_none(row["valid_from"]) if "valid_from" in row_keys else None,
            valid_until=self._parse_iso_or_none(row["valid_until"]) if "valid_until" in row_keys else None,
        )
