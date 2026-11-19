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
    def add_item(self, item: Item) -> Result[int, RepositoryError]:
        """item を追加（重複時は個数を加算）し、その行 id を返す。"""
        ...

    def find_item_by_name(self, name: str) -> Result[Item | None, RepositoryError]:
        """名前で Item を検索する（無ければ None）。"""
        ...

    def update_item(self, name: str, **kwargs: object) -> Result[Item, RepositoryError]:
        """名前をキーに Item の属性を更新する。"""
        ...

    def remove_item(self, name: str) -> Result[None, RepositoryError]:
        """名前をキーに Item を削除する。"""
        ...

    def search_items(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> Result[list[Item], RepositoryError]:
        """query/category で Item を検索する。"""
        ...

    # Equipment slots
    def equip_slot(self, slot: str, item_name: str) -> Result[None, RepositoryError]:
        """スロットに Item を装備する。"""
        ...

    def unequip_slot(self, slot: str) -> Result[None, RepositoryError]:
        """スロットの装備を外す。"""
        ...

    def get_all_slots(
        self,
    ) -> Result[list[EquipmentSlot], RepositoryError]:
        """全スロットの状態を返す。"""
        ...

    # History
    def add_history(self, entry: EquipmentHistory) -> Result[None, RepositoryError]:
        """装備履歴を1件追加する。"""
        ...
