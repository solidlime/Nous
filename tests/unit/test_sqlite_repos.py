"""Integration tests for SQLite repository implementations.

Each test uses tmp_path to create isolated SQLite databases.
"""

from __future__ import annotations

import pytest

from nous.domain.equipment.entities import Item
from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.persona.entities import EmotionRecord
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.equipment_repo import SQLiteEquipmentRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_conn(tmp_path):
    """Create a fresh SQLiteConnection in a temp directory."""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture
def memory_repo(sqlite_conn):
    return SQLiteMemoryRepository(sqlite_conn)


@pytest.fixture
def persona_repo(sqlite_conn):
    return SQLitePersonaRepository(sqlite_conn)


@pytest.fixture
def equipment_repo(sqlite_conn):
    return SQLiteEquipmentRepository(sqlite_conn)


# ---------------------------------------------------------------------------
# SQLiteMemoryRepository Tests
# ---------------------------------------------------------------------------


class TestSQLiteMemoryRepo:
    def _make_memory(self, key: str = "memory_20250101120000", content: str = "test") -> Memory:
        now = get_now()
        return Memory(key=key, content=content, created_at=now, updated_at=now)

    def test_save_and_find(self, memory_repo: SQLiteMemoryRepository):
        m = self._make_memory()
        save_result = memory_repo.save(m)
        assert save_result.is_ok
        assert save_result.unwrap() == m.key

        find_result = memory_repo.find_by_key(m.key)
        assert find_result.is_ok
        found = find_result.unwrap()
        assert found is not None
        assert found.content == "test"

    def test_find_nonexistent(self, memory_repo: SQLiteMemoryRepository):
        result = memory_repo.find_by_key("memory_99999999999999")
        assert result.is_ok
        assert result.unwrap() is None

    def test_update(self, memory_repo: SQLiteMemoryRepository):
        m = self._make_memory()
        memory_repo.save(m)
        result = memory_repo.update(m.key, content="updated content", importance=0.9)
        assert result.is_ok
        updated = result.unwrap()
        assert updated.content == "updated content"
        assert updated.importance == 0.9

    def test_update_nonexistent(self, memory_repo: SQLiteMemoryRepository):
        result = memory_repo.update("memory_99999999999999", content="x")
        assert not result.is_ok

    def test_delete(self, memory_repo: SQLiteMemoryRepository):
        m = self._make_memory()
        memory_repo.save(m)
        del_result = memory_repo.delete(m.key)
        assert del_result.is_ok
        find_result = memory_repo.find_by_key(m.key)
        assert find_result.is_ok
        assert find_result.unwrap() is None

    def test_count(self, memory_repo: SQLiteMemoryRepository):
        assert memory_repo.count().unwrap() == 0
        memory_repo.save(self._make_memory("memory_20250101000001", "a"))
        memory_repo.save(self._make_memory("memory_20250101000002", "b"))
        assert memory_repo.count().unwrap() == 2

    def test_find_recent(self, memory_repo: SQLiteMemoryRepository):
        for i in range(5):
            memory_repo.save(self._make_memory(f"memory_2025010100000{i}", f"m{i}"))
        result = memory_repo.find_recent(limit=3)
        assert result.is_ok
        assert len(result.unwrap()) == 3

    def test_find_all(self, memory_repo: SQLiteMemoryRepository):
        for i in range(3):
            memory_repo.save(self._make_memory(f"memory_2025010100000{i}", f"m{i}"))
        result = memory_repo.find_all()
        assert result.is_ok
        assert len(result.unwrap()) == 3

    def test_find_by_tags(self, memory_repo: SQLiteMemoryRepository):
        m1 = self._make_memory("memory_20250101000001", "food")
        m1.tags = ["food", "japanese"]
        m2 = self._make_memory("memory_20250101000002", "travel")
        m2.tags = ["travel"]
        memory_repo.save(m1)
        memory_repo.save(m2)
        result = memory_repo.find_by_tags(["food"])
        assert result.is_ok
        assert len(result.unwrap()) == 1
        assert result.unwrap()[0].content == "food"

    def test_search_keyword(self, memory_repo: SQLiteMemoryRepository):
        memory_repo.save(self._make_memory("memory_20250101000001", "I love ramen"))
        memory_repo.save(self._make_memory("memory_20250101000002", "sushi is great"))
        result = memory_repo.search_keyword("ramen")
        assert result.is_ok
        assert len(result.unwrap()) == 1
        assert result.unwrap()[0][0].content == "I love ramen"

    def test_save_and_get_strength(self, memory_repo: SQLiteMemoryRepository):
        m = self._make_memory()
        memory_repo.save(m)
        strength = MemoryStrength(memory_key=m.key, stability=2.0, recall_count=3)
        memory_repo.save_strength(strength)
        result = memory_repo.get_strength(m.key)
        assert result.is_ok
        s = result.unwrap()
        assert s is not None
        assert s.stability == 2.0
        assert s.recall_count == 3

    def test_save_and_get_block(self, memory_repo: SQLiteMemoryRepository):
        memory_repo.save_block("test_block", "block content", block_type="system")
        result = memory_repo.get_block("test_block")
        assert result.is_ok
        block = result.unwrap()
        assert block is not None
        assert block["content"] == "block content"
        assert block["block_type"] == "system"

    def test_list_and_delete_blocks(self, memory_repo: SQLiteMemoryRepository):
        memory_repo.save_block("b1", "c1")
        memory_repo.save_block("b2", "c2")
        assert len(memory_repo.list_blocks().unwrap()) == 2
        memory_repo.delete_block("b1")
        assert len(memory_repo.list_blocks().unwrap()) == 1


# ---------------------------------------------------------------------------
# SQLitePersonaRepository Tests
# ---------------------------------------------------------------------------

PERSONA = "test_persona"


class TestSQLitePersonaRepo:
    def test_update_and_get_state(self, persona_repo: SQLitePersonaRepository):
        persona_repo.update_state(PERSONA, "emotion", "joy")
        persona_repo.update_state(PERSONA, "physical_state", "relaxed")
        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.emotion == "joy"
        assert state.physical_state == "relaxed"

    def test_default_state(self, persona_repo: SQLitePersonaRepository):
        result = persona_repo.get_current_state(PERSONA)
        assert result.is_ok
        state = result.unwrap()
        assert state.emotion == "neutral"
        assert state.physical_state is None

    def test_bi_temporal_update(self, persona_repo: SQLitePersonaRepository):
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Asia/Tokyo")
        t1 = datetime(2025, 6, 15, 10, 0, 0, tzinfo=tz)
        t2 = t1 + timedelta(seconds=5)

        with patch("nous.infrastructure.sqlite.persona_repo.get_now", return_value=t1):
            persona_repo.update_state(PERSONA, "emotion", "joy")
        with patch("nous.infrastructure.sqlite.persona_repo.get_now", return_value=t2):
            persona_repo.update_state(PERSONA, "emotion", "sadness")

        result = persona_repo.get_current_state(PERSONA)
        assert result.unwrap().emotion == "sadness"
        history = persona_repo.get_state_history(PERSONA, "emotion")
        assert history.is_ok
        assert len(history.unwrap()) == 2

    def test_add_and_get_emotion_history(self, persona_repo: SQLitePersonaRepository):
        record = EmotionRecord(emotion="joy", intensity=0.8, timestamp=get_now(), context="good news")
        persona_repo.add_emotion_record(PERSONA, record)
        result = persona_repo.get_emotion_history(PERSONA)
        assert result.is_ok
        records = result.unwrap()
        assert len(records) == 1
        assert records[0].emotion == "joy"
        assert records[0].context == "good news"

    def test_user_info(self, persona_repo: SQLitePersonaRepository):
        persona_repo.set_user_info(PERSONA, "name", "太郎")
        persona_repo.set_user_info(PERSONA, "age", "25")
        result = persona_repo.get_user_info(PERSONA)
        assert result.is_ok
        info = result.unwrap()
        assert info["name"] == "太郎"
        assert info["age"] == "25"

    def test_persona_info(self, persona_repo: SQLitePersonaRepository):
        persona_repo.set_persona_info(PERSONA, "nickname", "ヘルタ")
        result = persona_repo.get_persona_info(PERSONA)
        assert result.is_ok
        assert result.unwrap()["nickname"] == "ヘルタ"


# ---------------------------------------------------------------------------
# SQLiteEquipmentRepository Tests
# ---------------------------------------------------------------------------


class TestSQLiteEquipmentRepo:
    def _make_item(self, name: str = "白いドレス", category: str = "clothing") -> Item:
        now = get_now()
        return Item(name=name, category=category, created_at=now, updated_at=now)

    def test_add_and_find_item(self, equipment_repo: SQLiteEquipmentRepository):
        item = self._make_item()
        result = equipment_repo.add_item(item)
        assert result.is_ok
        find_result = equipment_repo.find_item(item.name)
        assert find_result.is_ok
        found = find_result.unwrap()
        assert found is not None
        assert found.name == "白いドレス"
        assert found.category == "clothing"

    def test_add_duplicate_increments_quantity(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item("ポーション"))
        equipment_repo.add_item(Item(name="ポーション", quantity=3, created_at=get_now(), updated_at=get_now()))
        result = equipment_repo.find_item("ポーション")
        assert result.is_ok
        assert result.unwrap().quantity == 4  # 1 + 3

    def test_remove_item(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item("靴", "footwear"))
        result = equipment_repo.remove_item("靴")
        assert result.is_ok
        assert equipment_repo.find_item("靴").unwrap() is None

    def test_update_item(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item())
        result = equipment_repo.update_item("白いドレス", description="雨に濡れた状態")
        assert result.is_ok
        assert result.unwrap().description == "雨に濡れた状態"

    def test_equip_and_get(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item())
        result = equipment_repo.equip("top", "白いドレス")
        assert result.is_ok
        eq = equipment_repo.get_equipment()
        assert eq.is_ok
        assert eq.unwrap()["top"] == "白いドレス"

    def test_unequip(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item())
        equipment_repo.equip("top", "白いドレス")
        result = equipment_repo.unequip("top")
        assert result.is_ok
        eq = equipment_repo.get_equipment()
        assert eq.unwrap()["top"] is None

    def test_invalid_slot_equip(self, equipment_repo: SQLiteEquipmentRepository):
        result = equipment_repo.equip("invalid_slot", "item")
        assert not result.is_ok

    def test_invalid_slot_unequip(self, equipment_repo: SQLiteEquipmentRepository):
        result = equipment_repo.unequip("invalid_slot")
        assert not result.is_ok

    def test_list_items(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item("A", "clothing"))
        equipment_repo.add_item(self._make_item("B", "accessory"))
        result = equipment_repo.list_items()
        assert result.is_ok
        assert len(result.unwrap()) == 2

    def test_list_items_by_category(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.add_item(self._make_item("A", "clothing"))
        equipment_repo.add_item(self._make_item("B", "accessory"))
        result = equipment_repo.list_items(category="clothing")
        assert result.is_ok
        assert len(result.unwrap()) == 1

    def test_get_history(self, equipment_repo: SQLiteEquipmentRepository):
        equipment_repo.equip("top", "シャツ")
        result = equipment_repo.get_history(days=7)
        assert result.is_ok
        assert len(result.unwrap()) >= 1
