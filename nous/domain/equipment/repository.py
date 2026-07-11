from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nous.domain.equipment.entities import EquipmentHistory, EquipmentSlot, Item
    from nous.domain.shared.errors import RepositoryError
    from nous.domain.shared.result import Result


@runtime_checkable
class EquipmentRepository(Protocol):
    """Repository interface for equipment persistence."""

    # Item CRUD
    def add_item(self, item: Item) -> Result[Item, RepositoryError]: ...

    def find_item_by_name(self, name: str) -> Result[Item | None, RepositoryError]: ...

    def update_item(self, name: str, **kwargs: object) -> Result[Item, RepositoryError]: ...

    def remove_item(self, name: str) -> Result[None, RepositoryError]: ...

    def search_items(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> Result[list[Item], RepositoryError]: ...

    # Equipment slots
    def equip_slot(self, slot: str, item_name: str) -> Result[None, RepositoryError]: ...

    def unequip_slot(self, slot: str) -> Result[None, RepositoryError]: ...

    def get_all_slots(
        self,
    ) -> Result[list[EquipmentSlot], RepositoryError]: ...

    # History
    def add_history(self, entry: EquipmentHistory) -> Result[None, RepositoryError]: ...
