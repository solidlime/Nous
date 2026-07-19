from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.equipment.entities import (
    VALID_SLOTS,
    EquipmentHistory,
    Item,
)
from nous.domain.shared.errors import (
    DomainError,
    ItemNotFoundError,
    ItemValidationError,
)
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from nous.domain.equipment.repository import EquipmentRepository


class EquipmentService:
    """Domain service for equipment management."""

    def __init__(self, repo: EquipmentRepository) -> None:
        self._repo = repo

    def add_item(
        self,
        name: str,
        category: str | None = None,
        description: str | None = None,
        visual_desc: str | None = None,
        quantity: int = 1,
        tags: list[str] | None = None,
    ) -> Result[Item, DomainError]:
        """Add an item to inventory. Auto-increments quantity if exists."""
        if not name or not name.strip():
            return Failure(ItemValidationError("Item name must not be empty"))

        existing = self._repo.find_item_by_name(name.strip())
        if not existing.is_ok:
            return Failure(existing.error)

        if existing.value is not None:
            new_qty = existing.value.quantity + quantity
            result = self._repo.update_item(name.strip(), quantity=new_qty)
            if not result.is_ok:
                return Failure(result.error)
            self._repo.add_history(
                EquipmentHistory(
                    action="add",
                    item_name=name.strip(),
                    timestamp=get_now(),
                    details=f"quantity +{quantity} (total: {new_qty})",
                )
            )
            return result

        now = get_now()
        item = Item(
            name=name.strip(),
            category=category,
            description=description,
            visual_desc=visual_desc,
            quantity=quantity,
            tags=tags or [],
            created_at=now,
            updated_at=now,
        )
        result = self._repo.add_item(item)
        if result.is_ok:
            self._repo.add_history(
                EquipmentHistory(
                    action="add",
                    item_name=name.strip(),
                    timestamp=now,
                    details=f"new item (quantity: {quantity})",
                )
            )
        return result

    def remove_item(self, name: str) -> Result[None, DomainError]:
        """Remove an item and unequip from any slot."""
        existing = self._repo.find_item_by_name(name)
        if not existing.is_ok:
            return Failure(existing.error)
        if existing.value is None:
            return Failure(ItemNotFoundError(f"Item not found: {name}"))

        slots_result = self._repo.get_all_slots()
        if slots_result.is_ok:
            for slot in slots_result.value:
                if slot.item_name == name:
                    self._repo.unequip_slot(slot.slot)

        result = self._repo.remove_item(name)
        if result.is_ok:
            self._repo.add_history(
                EquipmentHistory(
                    action="remove",
                    item_name=name,
                    timestamp=get_now(),
                )
            )
        return result

    def update_item(self, name: str, **updates: object) -> Result[Item, DomainError]:
        """Update item fields. Supports renaming via item_name key."""
        existing = self._repo.find_item_by_name(name)
        if not existing.is_ok:
            return Failure(existing.error)
        if existing.value is None:
            return Failure(ItemNotFoundError(f"Item not found: {name}"))

        # Map API key item_name → repo field name
        if "item_name" in updates:
            updates["name"] = updates.pop("item_name")

        updates["updated_at"] = get_now()
        result = self._repo.update_item(name, **updates)
        if result.is_ok:
            self._repo.add_history(
                EquipmentHistory(
                    action="update",
                    item_name=name,
                    timestamp=get_now(),
                    details=str(list(updates.keys())),
                )
            )
        return result

    def equip(
        self,
        equipment: dict[str, str],
        auto_add: bool = True,
    ) -> Result[dict, DomainError]:
        """Equip items to slots. equipment is {slot: item_name}."""
        results: dict[str, str] = {}
        now = get_now()

        for slot, item_name in equipment.items():
            if slot not in VALID_SLOTS:
                return Failure(ItemValidationError(f"Invalid slot: {slot!r}. Valid: {VALID_SLOTS}"))

            if auto_add:
                existing = self._repo.find_item_by_name(item_name)
                if existing.is_ok and existing.value is None:
                    self._repo.add_item(
                        Item(
                            name=item_name,
                            created_at=now,
                            updated_at=now,
                        )
                    )

            equip_result = self._repo.equip_slot(slot, item_name)
            if not equip_result.is_ok:
                return Failure(equip_result.error)

            self._repo.add_history(
                EquipmentHistory(
                    action="equip",
                    item_name=item_name,
                    slot=slot,
                    timestamp=now,
                )
            )
            results[slot] = item_name

        return Success(results)

    def unequip(self, slots: list[str] | str) -> Result[None, DomainError]:
        """Unequip items from given slots."""
        if isinstance(slots, str):
            slots = [slots]

        for slot in slots:
            if slot not in VALID_SLOTS:
                return Failure(ItemValidationError(f"Invalid slot: {slot!r}. Valid: {VALID_SLOTS}"))

            slots_result = self._repo.get_all_slots()
            if slots_result.is_ok:
                for s in slots_result.value:
                    if s.slot == slot and s.item_name:
                        self._repo.add_history(
                            EquipmentHistory(
                                action="unequip",
                                item_name=s.item_name,
                                slot=slot,
                                timestamp=get_now(),
                            )
                        )

            result = self._repo.unequip_slot(slot)
            if not result.is_ok:
                return Failure(result.error)

        return Success(None)

    def search_items(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> Result[list[Item], DomainError]:
        """Search items by query string or category."""
        return self._repo.search_items(query=query, category=category)

    def get_equipment(self) -> Result[dict[str, str | None], DomainError]:
        """Get current equipment state as {slot: item_name}."""
        result = self._repo.get_all_slots()
        if not result.is_ok:
            return Failure(result.error)
        return Success({s.slot: s.item_name for s in result.value})

    def get_equipped_item_descs(self) -> Result[list[str], DomainError]:
        """Get visual_desc strings from all currently equipped items.

        Returns a list of ``visual_desc`` values for items that have one set.
        Items without a ``visual_desc`` (None or empty) are skipped.
        """
        equipment_result = self.get_equipment()
        if not equipment_result.is_ok:
            return Failure(equipment_result.error)

        descs: list[str] = []
        for _slot, item_name in equipment_result.value.items():
            if item_name is None:
                continue
            item_result = self._repo.find_item_by_name(item_name)
            if item_result.is_ok and item_result.value and item_result.value.visual_desc:
                descs.append(item_result.value.visual_desc)
        return Success(descs)
