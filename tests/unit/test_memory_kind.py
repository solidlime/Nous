"""Tests for Memory kind field validation."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nous.domain.memory.entities import VALID_KINDS, Memory

TZ = ZoneInfo("Asia/Tokyo")


def _make_memory(**overrides: object) -> Memory:
    now = datetime.now(TZ)
    defaults: dict = {
        "key": "memory_test_kind",
        "content": "test content",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Memory(**defaults)  # type: ignore[arg-type]


class TestMemoryKind:
    def test_kind_defaults_to_semantic(self) -> None:
        m = _make_memory()
        assert m.kind == "semantic"

    def test_kind_episodic_with_fields(self) -> None:
        m = _make_memory(
            kind="episodic",
            episodic_time="2025-06-15T14:00:00",
            episodic_place="Paris",
            episodic_people='["Alice", "Bob"]',
        )
        assert m.kind == "episodic"
        assert m.episodic_time == "2025-06-15T14:00:00"
        assert m.episodic_place == "Paris"
        assert m.episodic_people == '["Alice", "Bob"]'

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid kind"):
            _make_memory(kind="invalid_kind")

    def test_invalid_empty_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid kind"):
            _make_memory(kind="")

    def test_kind_procedural(self) -> None:
        m = _make_memory(kind="procedural")
        assert m.kind == "procedural"

    def test_kind_prospective(self) -> None:
        m = _make_memory(kind="prospective")
        assert m.kind == "prospective"

    def test_all_valid_kinds(self) -> None:
        for kind in VALID_KINDS:
            m = _make_memory(kind=kind)
            assert m.kind == kind
