from __future__ import annotations

import json
from datetime import timedelta

from nous.domain.equipment.entities import (
    EquipmentHistory,
    Item,
)
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now, parse_iso
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.base_repo import SQLiteRepository

logger = get_logger(__name__)

VALID_SLOTS = frozenset({"top", "bottom", "shoes", "outer", "head", "accessory_1", "accessory_2", "accessory_3"})


class SQLiteEquipmentRepository(SQLiteRepository):
    """SQLite-backed implementation of the EquipmentRepository protocol."""

    _db_method = "get_inventory_db"

    # ------------------------------------------------------------------
    # Item management
    # ------------------------------------------------------------------

    def add_item(self, item: Item) -> Result[int, RepositoryError]:
        """Add a new item. If it already exists, increment its quantity."""
        try:
            now = format_iso(get_now())
            existing = self._db.execute("SELECT id, quantity FROM items WHERE name = ?", (item.name,)).fetchone()

            if existing is not None:
                new_qty = existing["quantity"] + item.quantity
                self._db.execute(
                    "UPDATE items SET quantity = ?, updated_at = ? WHERE id = ?",
                    (new_qty, now, existing["id"]),
                )
                self._db.commit()
                logger.info("Item quantity updated: %s -> %d", item.name, new_qty)
                return Success(existing["id"])

            self._db.execute(
                """
                INSERT INTO items (name, category, description, visual_desc, quantity, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.name,
                    item.category,
                    item.description,
                    item.visual_desc,
                    item.quantity,
                    json.dumps(item.tags, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._db.commit()
            item_id = self._db.execute("SELECT id FROM items WHERE name = ?", (item.name,)).fetchone()["id"]
            logger.info("Item added: %s (id=%d)", item.name, item_id)
            return Success(item_id)
        except Exception as e:
            logger.error("Failed to add item %s: %s", item.name, e)
            return Failure(RepositoryError(str(e)))

    def remove_item(self, name: str) -> Result[None, RepositoryError]:
        """Remove an item by name."""
        try:
            self._db.execute("DELETE FROM items WHERE name = ?", (name,))
            self._db.commit()
            logger.info("Item removed: %s", name)
            return Success(None)
        except Exception as e:
            logger.error("Failed to remove item %s: %s", name, e)
            return Failure(RepositoryError(str(e)))

    def find_item(self, name: str) -> Result[Item | None, RepositoryError]:
        """Find an item by name."""
        try:
            row = self._db.execute("SELECT * FROM items WHERE name = ?", (name,)).fetchone()
            if row is None:
                return Success(None)
            return Success(self._row_to_item(row))
        except Exception as e:
            logger.error("Failed to find item %s: %s", name, e)
            return Failure(RepositoryError(str(e)))

    def list_items(self, category: str | None = None) -> Result[list[Item], RepositoryError]:
        """List all items, optionally filtered by category."""
        try:
            if category:
                rows = self._db.execute(
                    "SELECT * FROM items WHERE category = ? ORDER BY name",
                    (category,),
                ).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM items ORDER BY name").fetchall()
            return Success([self._row_to_item(r) for r in rows])
        except Exception as e:
            logger.error("Failed to list items: %s", e)
            return Failure(RepositoryError(str(e)))

    def update_item(self, name: str, **updates) -> Result[Item, RepositoryError]:
        """Update specific fields of an item."""
        try:
            existing = self._db.execute("SELECT * FROM items WHERE name = ?", (name,)).fetchone()
            if existing is None:
                return Failure(RepositoryError(f"Item not found: {name}"))

            fields: dict = {}
            for field, value in updates.items():
                if field == "tags":
                    fields[field] = json.dumps(value, ensure_ascii=False)
                else:
                    fields[field] = value
            fields["updated_at"] = format_iso(get_now())

            set_clause = ", ".join(f"{k} = ?" for k in fields)
            values = list(fields.values()) + [name]
            self._db.execute(
                f"UPDATE items SET {set_clause} WHERE name = ?",  # noqa: S608  # nosec B608
                values,
            )
            self._db.commit()

            updated_row = self._db.execute(
                "SELECT * FROM items WHERE name = ?",
                (updates.get("name", name),),
            ).fetchone()
            logger.info("Item updated: %s", name)
            return Success(self._row_to_item(updated_row))
        except Exception as e:
            logger.error("Failed to update item %s: %s", name, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Equipment slots
    # ------------------------------------------------------------------

    def equip(self, slot: str, item_name: str) -> Result[None, RepositoryError]:
        """Equip an item to a slot."""
        if slot not in VALID_SLOTS:
            return Failure(RepositoryError(f"Invalid slot: {slot}. Valid: {', '.join(sorted(VALID_SLOTS))}"))
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO equipment_slots (slot, item_name, equipped_at)
                VALUES (?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    item_name = excluded.item_name,
                    equipped_at = excluded.equipped_at
                """,
                (slot, item_name, now),
            )
            self._db.execute(
                """
                INSERT INTO equipment_history (action, slot, item_name, timestamp, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("equip", slot, item_name, now, None),
            )
            self._db.commit()
            logger.info("Equipped '%s' to slot '%s'", item_name, slot)
            return Success(None)
        except Exception as e:
            logger.error("Failed to equip %s to %s: %s", item_name, slot, e)
            return Failure(RepositoryError(str(e)))

    def unequip(self, slot: str) -> Result[None, RepositoryError]:
        """Unequip the item from a slot."""
        if slot not in VALID_SLOTS:
            return Failure(RepositoryError(f"Invalid slot: {slot}. Valid: {', '.join(sorted(VALID_SLOTS))}"))
        try:
            now = format_iso(get_now())
            current = self._db.execute("SELECT item_name FROM equipment_slots WHERE slot = ?", (slot,)).fetchone()
            item_name = current["item_name"] if current else None

            self._db.execute(
                """
                INSERT INTO equipment_slots (slot, item_name, equipped_at)
                VALUES (?, NULL, NULL)
                ON CONFLICT(slot) DO UPDATE SET
                    item_name = NULL,
                    equipped_at = NULL
                """,
                (slot,),
            )
            if item_name:
                self._db.execute(
                    """
                    INSERT INTO equipment_history (action, slot, item_name, timestamp, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("unequip", slot, item_name, now, None),
                )
            self._db.commit()
            logger.info("Unequipped slot '%s'", slot)
            return Success(None)
        except Exception as e:
            logger.error("Failed to unequip slot %s: %s", slot, e)
            return Failure(RepositoryError(str(e)))

    def get_equipment(self) -> Result[dict[str, str | None], RepositoryError]:
        """Get current equipment state for all slots."""
        try:
            rows = self._db.execute("SELECT slot, item_name FROM equipment_slots").fetchall()
            equipment = {slot: None for slot in VALID_SLOTS}
            for row in rows:
                equipment[row["slot"]] = row["item_name"]
            return Success(equipment)
        except Exception as e:
            logger.error("Failed to get equipment: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_history(self, days: int = 7) -> Result[list[EquipmentHistory], RepositoryError]:
        """Get equipment history for the last N days."""
        try:
            cutoff = format_iso(get_now() - timedelta(days=days))
            rows = self._db.execute(
                """
                SELECT * FROM equipment_history
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                """,
                (cutoff,),
            ).fetchall()
            return Success([self._row_to_history(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get equipment history: %s", e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Protocol aliases (EquipmentRepository protocol compliance)
    # ------------------------------------------------------------------

    def find_item_by_name(self, name: str) -> Result[Item | None, RepositoryError]:
        """Alias for ``find_item`` to satisfy the EquipmentRepository protocol."""
        return self.find_item(name)

    def equip_slot(self, slot: str, item_name: str) -> Result[None, RepositoryError]:
        """Alias for ``equip`` to satisfy the EquipmentRepository protocol."""
        return self.equip(slot, item_name)

    def unequip_slot(self, slot: str) -> Result[None, RepositoryError]:
        """Alias for ``unequip`` to satisfy the EquipmentRepository protocol."""
        return self.unequip(slot)

    def get_all_slots(self) -> Result[list, RepositoryError]:
        """Return all equipment slots as EquipmentSlot-like objects."""
        from nous.domain.equipment.entities import EquipmentSlot

        result = self.get_equipment()
        if not result.is_ok:
            return Failure(result.error)
        slots = []
        for slot_name, item_name in result.value.items():
            slots.append(EquipmentSlot(slot=slot_name, item_name=item_name))
        return Success(slots)

    def add_history(self, entry: EquipmentHistory) -> Result[None, RepositoryError]:
        """Add an equipment history entry."""
        try:
            self._db.execute(
                """
                INSERT INTO equipment_history (action, slot, item_name, timestamp, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry.action,
                    entry.slot,
                    entry.item_name,
                    format_iso(entry.timestamp) if entry.timestamp else format_iso(get_now()),
                    entry.details,
                ),
            )
            self._db.commit()
            return Success(None)
        except Exception as e:
            logger.error("Failed to add equipment history: %s", e)
            return Failure(RepositoryError(str(e)))

    def search_items(
        self, query: str | None = None, category: str | None = None
    ) -> Result[list[Item], RepositoryError]:
        """Search items by name substring and/or category."""
        try:
            if query and category:
                rows = self._db.execute(
                    "SELECT * FROM items WHERE name LIKE ? AND category = ? ORDER BY name",
                    (f"%{query}%", category),
                ).fetchall()
            elif query:
                rows = self._db.execute(
                    "SELECT * FROM items WHERE name LIKE ? ORDER BY name",
                    (f"%{query}%",),
                ).fetchall()
            elif category:
                rows = self._db.execute(
                    "SELECT * FROM items WHERE category = ? ORDER BY name",
                    (category,),
                ).fetchall()
            else:
                rows = self._db.execute("SELECT * FROM items ORDER BY name").fetchall()
            return Success([self._row_to_item(r) for r in rows])
        except Exception as e:
            logger.error("Failed to search items: %s", e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _row_to_item(self, row) -> Item:
        return Item(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            description=row["description"],
            visual_desc=row["visual_desc"] if "visual_desc" in row else None,  # noqa: SIM401 (sqlite3.Row has no .get)
            quantity=row["quantity"] or 1,
            tags=self._parse_json_list(row["tags"]),
            created_at=_parse_or_none(row["created_at"]),
            updated_at=_parse_or_none(row["updated_at"]),
        )

    @staticmethod
    def _row_to_history(row) -> EquipmentHistory:
        return EquipmentHistory(
            id=row["id"],
            action=row["action"],
            slot=row["slot"],
            item_name=row["item_name"],
            timestamp=_parse_or_none(row["timestamp"]),
            details=row["details"],
        )


def _parse_or_none(value: str | None):
    """Parse ISO datetime or return None."""
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:
        return None
