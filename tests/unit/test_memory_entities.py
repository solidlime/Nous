"""Tests for Memory domain entities."""

from datetime import datetime
from zoneinfo import ZoneInfo

from nous.domain.memory.entities import Memory

TZ = ZoneInfo("Asia/Tokyo")


class TestMemory:
    def test_create_with_defaults(self):
        now = datetime.now(TZ)
        m = Memory(key="memory_20250101120000", content="hello", created_at=now, updated_at=now)
        assert m.importance == 0.5
        assert m.emotion == "neutral"
        assert m.emotion_intensity == 0.0
        assert m.tags == []
        assert m.privacy_level == "internal"
        assert m.access_count == 0
        assert m.last_accessed is None
        assert m.related_keys == []

    def test_create_with_custom_values(self):
        now = datetime.now(TZ)
        m = Memory(
            key="memory_20250101120000",
            content="important event",
            created_at=now,
            updated_at=now,
            importance=0.9,
            emotion="joy",
            emotion_intensity=0.8,
            tags=["event", "special"],
            privacy_level="secret",
            physical_state="tired",
            mental_state="excited",
        )
        assert m.importance == 0.9
        assert m.emotion == "joy"
        assert m.tags == ["event", "special"]
        assert m.privacy_level == "secret"
        assert m.physical_state == "tired"

    def test_mutable_fields(self):
        now = datetime.now(TZ)
        m = Memory(key="memory_20250101120000", content="test", created_at=now, updated_at=now)
        m.content = "updated"
        m.importance = 0.8
        assert m.content == "updated"
        assert m.importance == 0.8
