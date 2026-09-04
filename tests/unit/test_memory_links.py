"""Unit tests for MemoryLink domain object — Hebbian co-activation + spontaneous decay."""

from __future__ import annotations

import pytest

from nous.domain.memory.memory_link import LINK_TYPES, MemoryLink


class TestMemoryLinkInit:
    """MemoryLink construction and validation."""

    def test_default_construction(self) -> None:
        link = MemoryLink(source_key="mem_a", target_key="mem_b")
        assert link.source_key == "mem_a"
        assert link.target_key == "mem_b"
        assert link.weight == 0.5
        assert link.link_type == "semantic"
        assert link.co_activation_count == 0
        assert link.last_activated is None

    def test_explicit_fields(self) -> None:
        link = MemoryLink(
            source_key="a",
            target_key="b",
            weight=0.8,
            link_type="temporal",
            co_activation_count=3,
            last_activated="2026-07-07T12:00:00+00:00",
        )
        assert link.weight == 0.8
        assert link.link_type == "temporal"
        assert link.co_activation_count == 3
        assert link.last_activated == "2026-07-07T12:00:00+00:00"

    def test_valid_link_types(self) -> None:
        for t in LINK_TYPES:
            link = MemoryLink("a", "b", link_type=t)
            assert link.link_type == t

    def test_invalid_link_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid link_type"):
            MemoryLink("a", "b", link_type="invalid_type")

    def test_empty_string_link_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid link_type"):
            MemoryLink("a", "b", link_type="")


class TestMemoryLinkDecay:
    """Spontaneous decay for unused links."""

    def test_decay_reduces_weight(self) -> None:
        link = MemoryLink("a", "b", weight=0.8)
        link.decay(rate=0.05)
        assert link.weight == 0.75

    def test_memory_link_decay(self) -> None:
        link = MemoryLink("a", "b", weight=0.5)
        link.decay()
        assert link.weight == 0.49

    def test_decay_floor_at_0_1(self) -> None:
        link = MemoryLink("a", "b", weight=0.1)
        link.decay(rate=0.05)
        assert link.weight == 0.1  # floor

    def test_decay_from_floor_repeated(self) -> None:
        link = MemoryLink("a", "b", weight=0.15)
        for _ in range(10):
            link.decay(rate=0.05)
        assert link.weight == 0.1  # stays at floor

    def test_decay_custom_rate(self) -> None:
        link = MemoryLink("a", "b", weight=1.0)
        link.decay(rate=0.2)
        assert link.weight == 0.8

    def test_decay_does_not_affect_count_or_activated(self) -> None:
        link = MemoryLink("a", "b", weight=0.7, co_activation_count=5, last_activated="2026-07-01T00:00:00+00:00")
        link.decay()
        assert link.co_activation_count == 5
        assert link.last_activated == "2026-07-01T00:00:00+00:00"
