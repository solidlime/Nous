from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.shared.errors import MigrationError
from nous.domain.shared.result import Failure, Result, Success

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class JSONLExporter:
    """Export all persona data to a JSONL standard format.

    Each line is a self-contained JSON object with a ``type`` field
    (``memory``, ``state``, ``item``, ``emotion``,
    ``strength``, ``goal``, ``promise``, ``equipment_slot``,
    ``equipment_history``).
    """

    def export_persona(
        self,
        connection: SQLiteConnection,
        persona: str,
        output_path: str,
    ) -> Result[int, MigrationError]:
        """Write every table's data for *persona* into *output_path*.

        Returns the total number of records written.
        """
        try:
            db = connection.get_memory_db()
            inv_db = connection.get_inventory_db()
            count = 0

            with open(output_path, "w", encoding="utf-8") as f:
                # memories
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM memories",
                    "memory",
                )

                # memory_strength
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM memory_strength",
                    "strength",
                )

                # context_state (filtered by persona)
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM context_state WHERE persona = ?",
                    "state",
                    params=(persona,),
                )

                # emotion_history
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM emotion_history",
                    "emotion",
                )

                # user_info (filtered by persona)
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM user_info WHERE persona = ?",
                    "user_info",
                    params=(persona,),
                )

                # persona_info (filtered by persona)
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM persona_info WHERE persona = ?",
                    "persona_info",
                    params=(persona,),
                )

                # goals
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM goals",
                    "goal",
                )

                # promises
                count += self._export_table(
                    f,
                    db,
                    "SELECT * FROM promises",
                    "promise",
                )

                # items
                count += self._export_table(
                    f,
                    inv_db,
                    "SELECT * FROM items",
                    "item",
                )

                # equipment_slots
                count += self._export_table(
                    f,
                    inv_db,
                    "SELECT * FROM equipment_slots",
                    "equipment_slot",
                )

                # equipment_history
                count += self._export_table(
                    f,
                    inv_db,
                    "SELECT * FROM equipment_history",
                    "equipment_history",
                )

            return Success(count)
        except Exception as exc:  # noqa: BLE001
            return Failure(MigrationError(f"Export failed: {exc}"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _export_table(
        file_handle,
        db,
        query: str,
        record_type: str,
        *,
        params: tuple = (),
    ) -> int:
        """Execute *query* and write each row as a JSONL line."""
        count = 0
        try:
            rows = db.execute(query, params).fetchall()
        except Exception:  # noqa: BLE001
            return 0

        for row in rows:
            record: dict = {"type": record_type, **dict(row)}
            file_handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            count += 1
        return count
