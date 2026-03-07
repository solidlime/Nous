"""
memory.db.MemoryDB のユニットテスト。

各テストは独立した一時 DB を使用し、テスト間で状態を共有しない。
"""

import os
import tempfile
from datetime import datetime

import pytest

import sys
sys.path.insert(0, "D:/VSCode/Nous")

from memory.db import MemoryDB
from memory.schema import MemoryEntry


def _make_db() -> tuple[MemoryDB, str]:
    """一時 SQLite DB と MemoryDB を作成して返す。"""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "test_persona", "memory.db")
    return MemoryDB(db_path), db_path


def _make_entry(key: str = "key_001", content: str = "テスト記憶") -> MemoryEntry:
    now = datetime.now().isoformat()
    return MemoryEntry(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        tags=["test"],
        importance=0.7,
    )


# ── 正常系 ────────────────────────────────────────────────────────────────────

def test_save_and_get_by_key_returns_entry():
    db, _ = _make_db()
    entry = _make_entry()
    assert db.save(entry) is True
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.key == entry.key
    assert result.content == entry.content


def test_save_multiple_and_get_recent():
    db, _ = _make_db()
    for i in range(3):
        db.save(_make_entry(key=f"key_{i:03d}", content=f"記憶{i}"))
    recent = db.get_recent(limit=10)
    assert len(recent) == 3


def test_delete_removes_entry():
    db, _ = _make_db()
    entry = _make_entry()
    db.save(entry)
    assert db.delete(entry.key) is True
    assert db.get_by_key(entry.key) is None


def test_increment_access_count_updates_count():
    db, _ = _make_db()
    entry = _make_entry()
    db.save(entry)
    db.increment_access_count(entry.key)
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.access_count == 1


def test_update_elevation_sets_fields():
    db, _ = _make_db()
    entry = _make_entry()
    db.save(entry)
    ok = db.update_elevation(entry.key, "物語的意味", "joy", 0.9)
    assert ok is True
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.elevated is True
    assert result.elevation_narrative == "物語的意味"
    assert result.elevation_emotion == "joy"
    assert result.elevation_significance == pytest.approx(0.9)


def test_get_stats_returns_dict():
    db, _ = _make_db()
    db.save(_make_entry())
    stats = db.get_stats()
    assert isinstance(stats, dict)
    assert "total" in stats


# ── 異常系・境界値 ────────────────────────────────────────────────────────────

def test_get_by_key_with_nonexistent_key_returns_none():
    db, _ = _make_db()
    assert db.get_by_key("nonexistent_key") is None


def test_delete_nonexistent_key_returns_true():
    db, _ = _make_db()
    # 存在しないキーの削除は例外を出さず True を返す（冪等）
    assert db.delete("ghost_key") is True


def test_importance_clamped_above_one():
    db, _ = _make_db()
    entry = _make_entry()
    entry.importance = 1.5
    db.save(entry)
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.importance <= 1.0


def test_importance_clamped_below_zero():
    db, _ = _make_db()
    entry = _make_entry()
    entry.importance = -0.5
    db.save(entry)
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.importance >= 0.0


def test_save_duplicate_key_replaces_entry():
    db, _ = _make_db()
    entry = _make_entry()
    db.save(entry)
    entry.content = "更新された内容"
    db.save(entry)
    result = db.get_by_key(entry.key)
    assert result is not None
    assert result.content == "更新された内容"


def test_get_recent_with_empty_db_returns_empty_list():
    db, _ = _make_db()
    result = db.get_recent(limit=5)
    assert result == []
