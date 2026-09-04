"""Tests for EquipmentService with an InMemory repository."""

from __future__ import annotations

from typing import Any

import pytest

from nous.domain.equipment.entities import (
    EquipmentHistory,
    EquipmentSlot,
    Item,
)
from nous.domain.equipment.service import EquipmentService
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success

# ---------------------------------------------------------------------------
# InMemory EquipmentRepository
# ---------------------------------------------------------------------------


class InMemoryEquipmentRepository:
    """Protocol-compatible in-memory repo for EquipmentService tests."""

    def __init__(self) -> None:
        self._items: dict[str, Item] = {}
        self._slots: dict[str, str | None] = {}
        self._history: list[EquipmentHistory] = []

    def add_item(self, item: Item) -> Result[Item, RepositoryError]:
        self._items[item.name] = item
        return Success(item)

    def find_item_by_name(self, name: str) -> Result[Item | None, RepositoryError]:
        return Success(self._items.get(name))

    def update_item(self, name: str, **kwargs: Any) -> Result[Item, RepositoryError]:
        if name not in self._items:
            return Failure(RepositoryError(f"Not found: {name}"))
        item = self._items[name]
        for field, value in kwargs.items():
            if hasattr(item, field):
                setattr(item, field, value)
        self._items[name] = item
        return Success(item)

    def remove_item(self, name: str) -> Result[None, RepositoryError]:
        self._items.pop(name, None)
        return Success(None)

    def search_items(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> Result[list[Item], RepositoryError]:
        results = list(self._items.values())
        if category:
            results = [i for i in results if i.category == category]
        if query:
            results = [
                i
                for i in results
                if query.lower() in (i.name or "").lower() or query.lower() in (i.description or "").lower()
            ]
        return Success(results)

    def equip_slot(self, slot: str, item_name: str) -> Result[None, RepositoryError]:
        self._slots[slot] = item_name
        return Success(None)

    def unequip_slot(self, slot: str) -> Result[None, RepositoryError]:
        self._slots[slot] = None
        return Success(None)

    def get_all_slots(
        self,
    ) -> Result[list[EquipmentSlot], RepositoryError]:
        return Success([EquipmentSlot(slot=s, item_name=n) for s, n in self._slots.items()])

    def add_history(self, entry: EquipmentHistory) -> Result[None, RepositoryError]:
        self._history.append(entry)
        return Success(None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return InMemoryEquipmentRepository()


@pytest.fixture
def service(repo):
    return EquipmentService(repo)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAddItem:
    def test_add_new_item(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        result = service.add_item("白いドレス", category="clothing")
        assert result.is_ok
        assert "白いドレス" in repo._items

    def test_add_increments_quantity(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.add_item("ポーション", quantity=3)
        service.add_item("ポーション", quantity=2)
        assert repo._items["ポーション"].quantity == 5

    def test_empty_name_fails(self, service: EquipmentService):
        result = service.add_item("")
        assert not result.is_ok

    def test_add_with_tags(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.add_item("帽子", tags=["accessory", "head"])
        assert repo._items["帽子"].tags == ["accessory", "head"]

    def test_add_with_visual_desc(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        """visual_desc should be set and retrievable."""
        service.add_item("古びた剣", visual_desc="錆びた刃、革の柄巻き")
        assert repo._items["古びた剣"].visual_desc == "錆びた刃、革の柄巻き"

    def test_visual_desc_defaults_none(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        """Items without visual_desc should have None."""
        service.add_item("普通の石")
        assert repo._items["普通の石"].visual_desc is None


class TestRemoveItem:
    def test_remove_existing(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.add_item("靴")
        result = service.remove_item("靴")
        assert result.is_ok
        assert "靴" not in repo._items

    def test_remove_nonexistent_fails(self, service: EquipmentService):
        result = service.remove_item("存在しない")
        assert not result.is_ok


class TestEquip:
    def test_equip_item(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.add_item("白いドレス")
        result = service.equip({"top": "白いドレス"})
        assert result.is_ok
        assert repo._slots.get("top") == "白いドレス"

    def test_equip_auto_add(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        result = service.equip({"shoes": "赤い靴"}, auto_add=True)
        assert result.is_ok
        assert "赤い靴" in repo._items
        assert repo._slots.get("shoes") == "赤い靴"

    def test_invalid_slot_fails(self, service: EquipmentService):
        result = service.equip({"invalid_slot": "item"})
        assert not result.is_ok

    def test_equip_records_history(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"head": "帽子"}, auto_add=True)
        equip_events = [h for h in repo._history if h.action == "equip"]
        assert len(equip_events) >= 1
        assert equip_events[-1].item_name == "帽子"

    def test_equip_multiple_slots(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        result = service.equip(
            {
                "top": "シャツ",
                "bottom": "スカート",
            },
            auto_add=True,
        )
        assert result.is_ok
        eq = result.value
        assert eq["top"] == "シャツ"
        assert eq["bottom"] == "スカート"


class TestUnequip:
    def test_unequip_slot(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"top": "ドレス"}, auto_add=True)
        result = service.unequip("top")
        assert result.is_ok
        assert repo._slots.get("top") is None

    def test_unequip_list(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"top": "A", "bottom": "B"}, auto_add=True)
        result = service.unequip(["top", "bottom"])
        assert result.is_ok

    def test_invalid_slot_fails(self, service: EquipmentService):
        result = service.unequip("invalid_slot")
        assert not result.is_ok


class TestSearchItems:
    def test_search_by_category(self, service: EquipmentService):
        service.add_item("白いドレス", category="clothing")
        service.add_item("赤いリング", category="accessory")
        result = service.search_items(category="clothing")
        assert result.is_ok
        assert len(result.value) == 1
        assert result.value[0].name == "白いドレス"

    def test_search_by_query(self, service: EquipmentService):
        service.add_item("白いドレス", description="シンプルな白ドレス")
        service.add_item("赤いドレス", description="派手な赤ドレス")
        result = service.search_items(query="白い")
        assert result.is_ok
        assert len(result.value) == 1

    def test_search_all(self, service: EquipmentService):
        service.add_item("A")
        service.add_item("B")
        result = service.search_items()
        assert result.is_ok
        assert len(result.value) == 2


class TestGetEquipment:
    def test_get_equipment_state(self, service: EquipmentService):
        service.equip({"top": "シャツ", "bottom": "パンツ"}, auto_add=True)
        result = service.get_equipment()
        assert result.is_ok
        eq = result.value
        assert eq["top"] == "シャツ"
        assert eq["bottom"] == "パンツ"


class TestBuildAppearance:
    """equip → appearance 自動合成 (Task: item スキル)."""

    def test_build_appearance_empty(self, service: EquipmentService):
        result = service.build_appearance({})
        assert result == ""

    def test_build_appearance_uses_item_name_fallback(
        self, service: EquipmentService, repo: InMemoryEquipmentRepository
    ):
        service.add_item("白いドレス")
        result = service.build_appearance({"top": "白いドレス"})
        assert result == "白いドレス"

    def test_build_appearance_prefers_visual_desc(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.add_item("白いドレス", visual_desc="white dress, off-shoulder")
        result = service.build_appearance({"top": "白いドレス"})
        assert result == "white dress, off-shoulder"

    def test_build_appearance_slot_order_follows_valid_slots(
        self, service: EquipmentService, repo: InMemoryEquipmentRepository
    ):
        service.equip(
            {"shoes": "黒い靴", "top": "白いドレス", "head": "黒いカチューシャ"},
            auto_add=True,
        )
        # VALID_SLOTS 順 (top → bottom → shoes → ... → head) に並ぶ
        result = service.build_appearance({"shoes": "黒い靴", "top": "白いドレス", "head": "黒いカチューシャ"})
        assert result == "白いドレス, 黒い靴, 黒いカチューシャ"

    def test_build_appearance_skips_none_or_empty_values(self, service: EquipmentService):
        result = service.build_appearance({"top": "ドレス", "shoes": "", "head": None})
        assert result == "ドレス"


class TestAccessorySlots:
    """accessory_1/2/3 スロットの拡張テスト."""

    def test_equip_accessory_1(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"accessory_1": "リング"}, auto_add=True)
        assert repo._slots.get("accessory_1") == "リング"

    def test_equip_accessory_2(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"accessory_2": "ネックレス"}, auto_add=True)
        assert repo._slots.get("accessory_2") == "ネックレス"

    def test_equip_accessory_3(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip({"accessory_3": "ブレスレット"}, auto_add=True)
        assert repo._slots.get("accessory_3") == "ブレスレット"

    def test_equip_all_three_accessories(self, service: EquipmentService, repo: InMemoryEquipmentRepository):
        service.equip(
            {
                "accessory_1": "リング",
                "accessory_2": "ネックレス",
                "accessory_3": "ブレスレット",
            },
            auto_add=True,
        )
        assert repo._slots.get("accessory_1") == "リング"
        assert repo._slots.get("accessory_2") == "ネックレス"
        assert repo._slots.get("accessory_3") == "ブレスレット"

    def test_old_accessories_slot_invalid(self, service: EquipmentService):
        service.add_item("指輪")
        result = service.equip({"accessories": "指輪"})
        assert not result.is_ok
        assert "Invalid slot" in str(result.error)
