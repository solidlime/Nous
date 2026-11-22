from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.shared.errors import MigrationError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class JSONLImporter:
    """Import memories and related data from a JSONL standard format.

    Each line is a JSON object with a ``type`` field that determines the
    target table.  Supported types: ``memory``, ``state``, ``item``,
    ``emotion``.
    """

    def import_file(
        self,
        file_path: str,
        connection: SQLiteConnection,
        persona: str,
    ) -> Result[dict, MigrationError]:
        """Read *file_path* line-by-line and dispatch to the appropriate
        table handler.

        Returns a dict mapping record types to imported counts.
        """
        counts: dict[str, int] = {
            "memory": 0,
            "state": 0,
            "item": 0,
            "emotion": 0,
        }

        try:
            with open(file_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data: dict = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    record_type = data.pop("type", "memory")

                    if record_type == "memory":
                        self._import_memory(data, connection, persona)
                        counts["memory"] += 1
                    elif record_type == "state":
                        self._import_state(data, connection, persona)
                        counts["state"] += 1
                    elif record_type == "item":
                        self._import_item(data, connection, persona)
                        counts["item"] += 1
                    elif record_type == "emotion":
                        self._import_emotion(data, connection)
                        counts["emotion"] += 1
        except OSError as exc:
            return Failure(MigrationError(f"Cannot read file: {exc}"))

        return Success(counts)

    # ------------------------------------------------------------------
    # Per-type handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _import_memory(data: dict, conn: SQLiteConnection, persona: str) -> None:  # noqa: ARG004
        db = conn.get_memory_db()
        now = format_iso(get_now())
        db.execute(
            """
            INSERT OR REPLACE INTO memories
            (key, content, created_at, updated_at, tags, importance,
             emotion, emotion_intensity, physical_state, mental_state,
             environment, relationship_status, action_tag,
             related_keys, summary_ref, equipped_items,
             access_count, last_accessed, privacy_level, source_context)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data.get("key", f"import_{now}"),
                data.get("content", ""),
                data.get("created_at", now),
                data.get("updated_at", now),
                data.get("tags", "[]"),
                data.get("importance", 0.5),
                data.get("emotion", "neutral"),
                data.get("emotion_intensity", 0.0),
                data.get("physical_state"),
                data.get("mental_state"),
                data.get("environment"),
                data.get("relationship_status"),
                data.get("action_tag"),
                data.get("related_keys", "[]"),
                data.get("summary_ref"),
                data.get("equipped_items"),
                data.get("access_count", 0),
                data.get("last_accessed"),
                data.get("privacy_level", "internal"),
                data.get("source_context", "jsonl_import"),
            ),
        )
        db.commit()

    @staticmethod
    def _import_state(data: dict, conn: SQLiteConnection, persona: str) -> None:
        db = conn.get_memory_db()
        now = format_iso(get_now())
        db.execute(
            """
            INSERT OR REPLACE INTO context_state
            (persona, key, value, valid_from, change_source)
            VALUES (?,?,?,?,?)
            """,
            (
                data.get("persona", persona),
                data.get("key", ""),
                data.get("value", ""),
                data.get("valid_from", now),
                data.get("change_source", "jsonl_import"),
            ),
        )
        db.commit()

    @staticmethod
    def _import_item(data: dict, conn: SQLiteConnection, persona: str) -> None:  # noqa: ARG004
        db = conn.get_inventory_db()
        now = format_iso(get_now())
        db.execute(
            """
            INSERT OR REPLACE INTO items
            (name, category, description, quantity, tags, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                data.get("name", "unknown"),
                data.get("category"),
                data.get("description"),
                data.get("quantity", 1),
                data.get("tags", "[]"),
                data.get("created_at", now),
                data.get("updated_at", now),
            ),
        )
        db.commit()

    @staticmethod
    def _import_emotion(data: dict, conn: SQLiteConnection) -> None:
        db = conn.get_memory_db()
        now = format_iso(get_now())
        db.execute(
            """
            INSERT INTO emotion_history
            (emotion_type, intensity, timestamp, trigger_memory_key, context)
            VALUES (?,?,?,?,?)
            """,
            (
                data.get("emotion_type", "neutral"),
                data.get("intensity", 0.5),
                data.get("timestamp", now),
                data.get("trigger_memory_key"),
                data.get("context"),
            ),
        )
        db.commit()
