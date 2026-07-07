"""Tests for Memory source provenance fields."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nous.domain.memory.entities import VALID_SOURCE_TYPES, Memory

TZ = ZoneInfo("Asia/Tokyo")


def _make_memory(**overrides: object) -> Memory:
    now = datetime.now(TZ)
    defaults: dict = {
        "key": "memory_test_prov",
        "content": "test content",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Memory(**defaults)  # type: ignore[arg-type]


class TestSourceProvenance:
    def test_default_source_type(self) -> None:
        m = _make_memory()
        assert m.source_type == "user_stated"
        assert m.confidence == 1.0
        assert m.derived_from is None

    def test_reflected_with_confidence(self) -> None:
        m = _make_memory(
            source_type="reflected",
            confidence=0.75,
            derived_from='["mem_001", "mem_002"]',
        )
        assert m.source_type == "reflected"
        assert m.confidence == 0.75
        assert m.derived_from == '["mem_001", "mem_002"]'

    def test_consolidated_without_derivation(self) -> None:
        m = _make_memory(source_type="consolidated", confidence=0.5)
        assert m.source_type == "consolidated"
        assert m.derived_from is None

    def test_invalid_source_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid source_type"):
            _make_memory(source_type="invalid_type")

    def test_all_valid_source_types(self) -> None:
        for st in VALID_SOURCE_TYPES:
            m = _make_memory(source_type=st)
            assert m.source_type == st
