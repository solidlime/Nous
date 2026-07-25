from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from nous.domain.shared.errors import MigrationError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class LegacyImporter:
    """Import legacy MemoryMCP v1 data into Nous v2/v3 schema.

    Expects a persona directory (or zip) containing:
    - ``memory.sqlite``  (memories, emotion_history, user_state,
      memory_strength, memory_blocks, goals, promises)
    - ``inventory.sqlite`` (items, equipment_slots, equipment_history)
    - ``persona_context.json``
    """

    def __init__(self, target_connection: SQLiteConnection, persona: str) -> None:
        self.target = target_connection
        self.persona = persona

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def import_from_directory(self, source_dir: str) -> Result[dict, MigrationError]:
        """Import all data from a legacy persona directory.

        Returns a dict mapping table names to imported record counts.
        """
        source_dir_path = Path(source_dir)
        counts: dict[str, int] = {}

        # 1. memory.sqlite
        memory_db_path = source_dir_path / "memory.sqlite"
        if memory_db_path.exists():
            src = sqlite3.connect(str(memory_db_path))
            src.row_factory = sqlite3.Row
            try:
                counts["memories"] = self._import_memories(src)
                counts["memory_strength"] = self._import_memory_strength(src)
                counts["memory_blocks"] = self._import_memory_blocks(src)
                counts["emotion_history"] = self._import_emotion_history(src)
                counts["user_state"] = self._import_user_state(src)
                counts["goals"] = self._import_goals(src)
                counts["promises"] = self._import_promises(src)
            finally:
                src.close()

        # 2. inventory.sqlite
        inventory_db_path = source_dir_path / "inventory.sqlite"
        if inventory_db_path.exists():
            src = sqlite3.connect(str(inventory_db_path))
            src.row_factory = sqlite3.Row
            try:
                counts["items"] = self._import_items(src)
                counts["equipment_slots"] = self._import_equipment_slots(src)
                counts["equipment_history"] = self._import_equipment_history(src)
            finally:
                src.close()
        else:
            logger.warning("inventory.sqlite not found in %s — skipping inventory import", source_dir_path)

        # 3. persona_context.json → context_state + user_info + persona_info
        context_path = source_dir_path / "persona_context.json"
        if context_path.exists():
            counts["persona_context"] = self._import_persona_context(context_path)

        # Refresh memory count after persona_context import
        # (_import_persona_context may add goals/promises directly to memories table)
        try:
            target_db = self.target.get_memory_db()
            counts["memories"] = target_db.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Import skip: %s", exc, exc_info=True)

        return Success(counts)

    def import_from_zip(self, zip_path: str) -> Result[dict, MigrationError]:
        """Import from a zip file containing legacy data."""
        zip_file = Path(zip_path)
        if not zip_file.exists():
            return Failure(MigrationError(f"Zip file not found: {zip_file}"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(zip_file, "r") as zf:
                for member in zf.namelist():
                    member_path = (Path(tmp_dir) / member).resolve()
                    if not str(member_path).startswith(str(Path(tmp_dir).resolve()) + os.sep) and str(
                        member_path
                    ) != str(Path(tmp_dir).resolve()):
                        return Failure(MigrationError(f"Zip Slip detected: {member}"))
                    zf.extract(member, tmp_dir)

            extracted = Path(tmp_dir)
            source_dir = self._find_source_dir(extracted)
            return self.import_from_directory(str(source_dir))

    def _find_source_dir(self, root: Path) -> Path:
        """Find the directory containing persona data files (memory.sqlite etc.).

        Searches recursively so that zips with nested folder structures work
        correctly regardless of depth.
        """
        for db_file in root.rglob("memory.sqlite"):
            return db_file.parent
        for db_file in root.rglob("inventory.sqlite"):
            return db_file.parent
        for json_file in root.rglob("persona_context.json"):
            return json_file.parent
        subdirs = [d for d in root.iterdir() if d.is_dir()]
        return subdirs[0] if subdirs else root

    # ------------------------------------------------------------------
    # Private — per-table import helpers
    # ------------------------------------------------------------------

    def _import_memories(self, src_db: sqlite3.Connection) -> int:
        """Copy memories from source DB.  ``source_context`` is set to
        ``'legacy_import'`` for every migrated row."""
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM memories").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
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
                        row["key"],
                        row["content"],
                        row["created_at"],
                        row["updated_at"],
                        row["tags"],
                        row["importance"],
                        row["emotion"],
                        row["emotion_intensity"],
                        row["physical_state"],
                        row["mental_state"],
                        row["environment"],
                        row["relationship_status"],
                        row["action_tag"],
                        row["related_keys"],
                        row["summary_ref"],
                        row["equipped_items"],
                        row["access_count"],
                        row["last_accessed"],
                        row["privacy_level"],
                        "legacy_import",
                    ),
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import skip: %s", exc, exc_info=True)
                continue

        target_db.commit()
        return count

    def _import_memory_strength(self, src_db: sqlite3.Connection) -> int:
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM memory_strength").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO memory_strength
                    (memory_key, strength, stability, last_decay,
                     recall_count, last_recall)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        row["memory_key"],
                        row["strength"],
                        row["stability"],
                        row["last_decay"],
                        row["recall_count"],
                        row["last_recall"],
                    ),
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import skip: %s", exc, exc_info=True)
                continue

        target_db.commit()
        return count

    def _import_memory_blocks(self, src_db: sqlite3.Connection) -> int:
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM memory_blocks").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO memory_blocks
                    (block_name, content, block_type, max_tokens,
                     priority, created_at, updated_at, metadata)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["block_name"],
                        row["content"],
                        row["block_type"],
                        row["max_tokens"],
                        row["priority"],
                        row["created_at"],
                        row["updated_at"],
                        row["metadata"],
                    ),
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import skip: %s", exc, exc_info=True)
                continue

        target_db.commit()
        return count

    def _import_emotion_history(self, src_db: sqlite3.Connection) -> int:
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM emotion_history").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO emotion_history
                    (id, emotion_type, intensity, timestamp,
                     trigger_memory_key, context)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        row["id"],
                        row["emotion_type"],
                        row["intensity"],
                        row["timestamp"],
                        row["trigger_memory_key"],
                        row["context"],
                    ),
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import skip: %s", exc, exc_info=True)
                continue

        target_db.commit()
        return count

    def _import_user_state(self, src_db: sqlite3.Connection) -> int:
        """Import legacy ``user_state`` rows into the new ``context_state`` table.

        The legacy table uses bi-temporal columns that map directly to
        ``context_state(persona, key, value, valid_from, valid_until,
        change_source)``.
        """
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM user_state").fetchall()
        except sqlite3.OperationalError:
            return 0

        col_names = [desc[0] for desc in src_db.execute("SELECT * FROM user_state LIMIT 0").description]

        for row in rows:
            try:
                persona = row["persona"] if "persona" in col_names else self.persona
                key = row["key"] if "key" in col_names else ""
                value = row["value"] if "value" in col_names else ""
                valid_from = row["valid_from"] if "valid_from" in col_names else format_iso(get_now())
                valid_until = row["valid_until"] if "valid_until" in col_names else None
                change_source = row["change_source"] if "change_source" in col_names else "legacy_import"

                target_db.execute(
                    """
                    INSERT OR REPLACE INTO context_state
                    (persona, key, value, valid_from, valid_until, change_source)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (persona, key, value, valid_from, valid_until, change_source),
                )
                count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Import skip: %s", exc, exc_info=True)
                continue

        target_db.commit()
        return count

    def _import_goals(self, src_db: sqlite3.Connection) -> int:
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM goals").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO goals
                    (id, description, status, priority,
                     created_at, updated_at, completed_at, metadata)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["id"],
                        row["description"],
                        row["status"],
                        row["priority"],
                        row["created_at"],
                        row["updated_at"],
                        row["completed_at"],
                        row["metadata"],
                    ),
                )
                count += 1
            except Exception:  # noqa: BLE001
                continue

        target_db.commit()
        return count

    def _import_promises(self, src_db: sqlite3.Connection) -> int:
        target_db = self.target.get_memory_db()
        count = 0

        try:
            rows = src_db.execute("SELECT * FROM promises").fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO promises
                    (id, description, status, priority,
                     created_at, updated_at, fulfilled_at, metadata)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        row["id"],
                        row["description"],
                        row["status"],
                        row["priority"],
                        row["created_at"],
                        row["updated_at"],
                        row["fulfilled_at"],
                        row["metadata"],
                    ),
                )
                count += 1
            except Exception:  # noqa: BLE001
                continue

        target_db.commit()
        return count

    def _import_items(self, src_db: sqlite3.Connection) -> int:
        """Import items from v1 inventory.sqlite.

        v1 schema: items(item_id, item_name, description, category, tags, created_at)
                 + inventory(persona, item_id, quantity, is_equipped, equipped_slot, acquired_at)
        v2 schema: items(id INTEGER, name, category, description, quantity, tags, created_at, updated_at)
        """
        target_db = self.target.get_inventory_db()
        count = 0

        # Detect schema version by checking column names
        try:
            cols = {r[1] for r in src_db.execute("PRAGMA table_info(items)").fetchall()}
        except sqlite3.OperationalError as e:
            logger.warning("Source DB has no 'items' table: %s", e)
            return 0

        is_v1 = "item_id" in cols  # v1 uses item_id/item_name

        if is_v1:
            # Join items with inventory to get quantity
            try:
                rows = src_db.execute(
                    """
                    SELECT i.item_id, i.item_name, i.category, i.description,
                           i.tags, i.created_at,
                           COALESCE(inv.quantity, 1) AS quantity
                    FROM items i
                    LEFT JOIN inventory inv USING (item_id)
                    GROUP BY i.item_id
                    """
                ).fetchall()
            except sqlite3.OperationalError:
                rows = src_db.execute("SELECT * FROM items").fetchall()
        else:
            rows = src_db.execute("SELECT * FROM items").fetchall()

        logger.info("Importing %d items from source DB (v1=%s)", len(rows), is_v1)
        for row in rows:
            try:
                if is_v1:
                    name = row["item_name"]
                    created_at = row["created_at"]
                    target_db.execute(
                        """
                        INSERT OR REPLACE INTO items
                        (name, category, description, quantity,
                         tags, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?)
                        """,
                        (
                            name,
                            row["category"],
                            row["description"],
                            row["quantity"],
                            row["tags"] or "[]",
                            created_at,
                            created_at,
                        ),
                    )
                else:
                    target_db.execute(
                        """
                        INSERT OR REPLACE INTO items
                        (id, name, category, description, quantity,
                         tags, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            row["id"],
                            row["name"],
                            row["category"],
                            row["description"],
                            row["quantity"],
                            row["tags"],
                            row["created_at"],
                            row["updated_at"],
                        ),
                    )
                count += 1
            except Exception as e:  # noqa: BLE001
                item_label = row["item_name"] if is_v1 else row.get("name", "?")
                logger.warning("Skipping item '%s': %s", item_label, e)
                continue

        target_db.commit()
        logger.info("Imported %d/%d items", count, len(rows))
        return count

    def _import_equipment_slots(self, src_db: sqlite3.Connection) -> int:
        """Import equipment slots from v1 inventory.sqlite.

        v1 schema: inventory(persona, item_id, is_equipped, equipped_slot, ...)
                   items(item_id, item_name, ...)
        v2 schema: equipment_slots(slot, item_name, equipped_at)
        """
        target_db = self.target.get_inventory_db()
        count = 0

        # Detect v1 vs v2
        try:
            cols = {r[1] for r in src_db.execute("PRAGMA table_info(items)").fetchall()}
        except sqlite3.OperationalError:
            cols = set()

        is_v1 = "item_id" in cols

        if is_v1:
            try:
                rows = src_db.execute(
                    """
                    SELECT inv.equipped_slot AS slot,
                           i.item_name       AS item_name,
                           inv.acquired_at   AS equipped_at
                    FROM inventory inv
                    JOIN items i USING (item_id)
                    WHERE inv.is_equipped = 1
                      AND inv.equipped_slot IS NOT NULL
                    """
                ).fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("Could not read v1 inventory for equipment_slots: %s", e)
                return 0
        else:
            try:
                rows = src_db.execute("SELECT * FROM equipment_slots").fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("Source DB has no 'equipment_slots' table: %s", e)
                return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO equipment_slots
                    (slot, item_name, equipped_at)
                    VALUES (?,?,?)
                    """,
                    (
                        row["slot"],
                        row["item_name"],
                        row["equipped_at"],
                    ),
                )
                count += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("Skipping equipment_slot '%s': %s", row.get("slot", "?"), e)
                continue

        target_db.commit()
        logger.info("Imported %d equipment slots (v1=%s)", count, is_v1)
        return count

    def _import_equipment_history(self, src_db: sqlite3.Connection) -> int:
        """Import equipment history from v1 inventory.sqlite.

        v1 schema: equipment_history(id, persona, item_id, slot, action, timestamp)
                   items(item_id, item_name)
        v2 schema: equipment_history(id, action, slot, item_name, timestamp, details)
        """
        target_db = self.target.get_inventory_db()
        count = 0

        # Detect v1 vs v2
        try:
            cols = {r[1] for r in src_db.execute("PRAGMA table_info(equipment_history)").fetchall()}
        except sqlite3.OperationalError as e:
            logger.warning("Source DB has no 'equipment_history' table: %s", e)
            return 0

        is_v1 = "item_id" in cols  # v1 uses item_id FK, v2 uses item_name TEXT

        if is_v1:
            try:
                rows = src_db.execute(
                    """
                    SELECT eh.id, eh.action, eh.slot, eh.timestamp,
                           i.item_name
                    FROM equipment_history eh
                    LEFT JOIN items i USING (item_id)
                    """
                ).fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("Could not read v1 equipment_history: %s", e)
                return 0
        else:
            try:
                rows = src_db.execute("SELECT * FROM equipment_history").fetchall()
            except sqlite3.OperationalError as e:
                logger.warning("Source DB has no 'equipment_history' table: %s", e)
                return 0

        for row in rows:
            try:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO equipment_history
                    (id, action, slot, item_name, timestamp, details)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        row["id"],
                        row["action"],
                        row["slot"],
                        row["item_name"],
                        row["timestamp"],
                        None,  # v1 has no details column
                    ),
                )
                count += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("Skipping equipment_history row: %s", e)
                continue

        target_db.commit()
        logger.info("Imported %d equipment_history rows (v1=%s)", count, is_v1)
        return count

    # ------------------------------------------------------------------
    # persona_context.json → context_state + user_info + persona_info
    # ------------------------------------------------------------------

    def _import_persona_context(self, json_path: Path) -> int:
        """Import persona_context.json into structured tables."""
        with open(json_path, encoding="utf-8") as f:
            data: dict = json.load(f)

        target_db = self.target.get_memory_db()
        now = format_iso(get_now())
        count = 0

        # Scalar state fields → context_state
        state_mappings: dict[str, str] = {
            "current_emotion": "emotion",
            "current_emotion_intensity": "emotion_intensity",
            "physical_state": "physical_state",
            "mental_state": "mental_state",
            "environment": "environment",
            "relationship_status": "relationship_status",
            "current_action_tag": "action_tag",
            "last_conversation_time": "last_conversation_time",
        }

        for json_key, state_key in state_mappings.items():
            value = data.get(json_key)
            if value is not None:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO context_state
                    (persona, key, value, valid_from, change_source)
                    VALUES (?,?,?,?,?)
                    """,
                    (self.persona, state_key, str(value), now, "legacy_import"),
                )
                count += 1

        # physical_sensations → context_state (each sensation as its own key)
        sensations: dict = data.get("physical_sensations", {})
        for sense_key, sense_val in sensations.items():
            if sense_val is not None:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO context_state
                    (persona, key, value, valid_from, change_source)
                    VALUES (?,?,?,?,?)
                    """,
                    (self.persona, sense_key, str(sense_val), now, "legacy_import"),
                )
                count += 1

        # current_goals → memories table (tags=["goal","active"])
        goals_raw = data.get("current_goals", [])
        if isinstance(goals_raw, str):
            goals_raw = [goals_raw] if goals_raw.strip() else []
        for i, goal in enumerate(goals_raw):
            goal_text = goal if isinstance(goal, str) else json.dumps(goal, ensure_ascii=False)
            goal_key = f"legacy_goal_{i}"
            target_db.execute(
                """
                INSERT OR IGNORE INTO memories
                (key, content, created_at, updated_at, tags, importance, emotion,
                 emotion_intensity, privacy_level, access_count)
                VALUES (?, ?, ?, ?, ?, 0.8, 'anticipation', 0.5, 'internal', 0)
                """,
                (goal_key, goal_text, now, now, '["goal","active"]'),
            )
            count += 1

        # active_promises → memories table (tags=["promise","active"])
        promises_raw = data.get("active_promises", [])
        if isinstance(promises_raw, str):
            promises_raw = [promises_raw] if promises_raw.strip() else []
        for i, promise in enumerate(promises_raw):
            promise_text = promise if isinstance(promise, str) else json.dumps(promise, ensure_ascii=False)
            promise_key = f"legacy_promise_{i}"
            target_db.execute(
                """
                INSERT OR IGNORE INTO memories
                (key, content, created_at, updated_at, tags, importance, emotion,
                 emotion_intensity, privacy_level, access_count)
                VALUES (?, ?, ?, ?, ?, 0.8, 'trust', 0.5, 'internal', 0)
                """,
                (promise_key, promise_text, now, now, '["promise","active"]'),
            )
            count += 1

        # anniversaries → context_state (serialised as JSON)
        anniversaries = data.get("anniversaries", [])
        if anniversaries:
            target_db.execute(
                """
                INSERT OR REPLACE INTO context_state
                (persona, key, value, valid_from, change_source)
                VALUES (?,?,?,?,?)
                """,
                (
                    self.persona,
                    "anniversaries",
                    json.dumps(anniversaries, ensure_ascii=False),
                    now,
                    "legacy_import",
                ),
            )
            count += 1

        # user_info → user_info table
        user_info: dict = data.get("user_info", {})
        for k, v in user_info.items():
            if v is not None:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO user_info
                    (persona, key, value, updated_at)
                    VALUES (?,?,?,?)
                    """,
                    (self.persona, k, str(v), now),
                )
                count += 1

        # persona_info → persona_info table
        persona_info: dict = data.get("persona_info", {})
        for k, v in persona_info.items():
            if v is not None:
                target_db.execute(
                    """
                    INSERT OR REPLACE INTO persona_info
                    (persona, key, value, updated_at)
                    VALUES (?,?,?,?)
                    """,
                    (self.persona, k, str(v), now),
                )
                count += 1

        target_db.commit()
        return count
