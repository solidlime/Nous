"""Tests for Sudachi-based NER extractor and hybrid extractor."""

from __future__ import annotations

import pytest


@pytest.mark.slow
def test_sudachi_extracts_person() -> None:
    from nous.domain.memory.sudachi_extractor import SudachiExtractor

    extractor = SudachiExtractor()
    entities = extractor.extract("田中さんが東京で会議に参加した")
    names = [e["name"] for e in entities]
    assert any("田中" in n for n in names)


@pytest.mark.slow
def test_sudachi_extracts_location() -> None:
    from nous.domain.memory.sudachi_extractor import SudachiExtractor

    extractor = SudachiExtractor()
    entities = extractor.extract("田中さんが東京で会議に参加した")
    names = [e["name"] for e in entities]
    assert any("東京" in n for n in names)


def test_hybrid_fast_path_works() -> None:
    from nous.domain.memory.sudachi_extractor import HybridEntityExtractor

    extractor = HybridEntityExtractor()
    entities = extractor.extract_fast("田中さんが東京で会議に参加した")
    # regex fallback should at least extract the honorific name
    assert len(entities) >= 1


@pytest.mark.slow
@pytest.mark.asyncio
async def test_hybrid_slow_path_works() -> None:
    from nous.domain.memory.sudachi_extractor import HybridEntityExtractor

    extractor = HybridEntityExtractor()
    entities = await extractor.extract_accurate("田中さんが東京で会議に参加した")
    assert len(entities) >= 2
