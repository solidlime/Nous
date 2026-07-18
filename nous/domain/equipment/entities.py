from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

VALID_SLOTS: list[str] = ["top", "bottom", "shoes", "outer", "head", "accessory_1", "accessory_2", "accessory_3"]


@dataclass
class Item:
    """A physical item in the inventory."""

    name: str
    category: str | None = None
    description: str | None = None
    visual_desc: str | None = None
    quantity: int = 1
    tags: list[str] = field(default_factory=list)
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class EquipmentSlot:
    """An equipment slot assignment."""

    slot: str
    item_name: str | None = None
    equipped_at: datetime | None = None


@dataclass
class EquipmentHistory:
    """Equipment change history entry."""

    action: str  # "equip" | "unequip" | "add" | "remove" | "update"
    item_name: str
    slot: str | None = None
    timestamp: datetime | None = None
    details: str | None = None
    id: int | None = None
