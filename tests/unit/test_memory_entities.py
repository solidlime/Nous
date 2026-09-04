"""Tests for Memory domain entities."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nous.domain.memory.entities import Memory, MemoryStrength

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


class TestMemoryStrength:
    def test_defaults(self):
        s = MemoryStrength(memory_key="memory_20250101120000")
        assert s.strength == 1.0
        assert s.stability == 1.0
        assert s.recall_count == 0

    def test_compute_recall_at_zero_hours(self):
        s = MemoryStrength(memory_key="k")
        assert s.compute_recall(0.0) == pytest.approx(1.0)

    def test_compute_recall_decays_over_time(self):
        s = MemoryStrength(memory_key="k", stability=1.0)
        r24 = s.compute_recall(24.0)  # 1 day elapsed, stability=1 day => FSRS: 20^(-0.5) ≈ 0.224
        assert r24 == pytest.approx(20**-0.5, rel=1e-5)

    def test_higher_stability_slower_decay(self):
        s_low = MemoryStrength(memory_key="k", stability=1.0)
        s_high = MemoryStrength(memory_key="k", stability=10.0)
        elapsed = 48.0  # 2 days
        assert s_high.compute_recall(elapsed) > s_low.compute_recall(elapsed)

    def test_compute_recall_zero_stability(self):
        s = MemoryStrength(memory_key="k", stability=0.0)
        assert s.compute_recall(1.0) == 0.0

    def test_boost_on_recall(self):
        s = MemoryStrength(memory_key="k", stability=1.0, recall_count=0)
        s.boost_on_recall()
        assert s.recall_count == 1
        assert s.stability == 1.5
        assert s.strength == 1.0

    def test_boost_caps_stability(self):
        s = MemoryStrength(memory_key="k", stability=300.0)
        s.boost_on_recall()
        assert s.stability == min(300.0 * 1.5, 365.0)

    def test_multiple_boosts(self):
        s = MemoryStrength(memory_key="k", stability=1.0)
        for _ in range(5):
            s.boost_on_recall()
        assert s.recall_count == 5
        assert s.stability == pytest.approx(1.0 * 1.5**5, rel=1e-5)
