"""Tests for Sudachi-based NER extractor and hybrid extractor."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def sudachi_extractor():
    """辞書が無ければ初回だけダウンロードする。取得できない環境は skip。

    辞書の取得はネットワーク越しなので、CDN 障害でユニットテストを赤にしない。
    """
    from nous.domain.memory.sudachi_extractor import SudachiExtractor

    try:
        return SudachiExtractor()
    except Exception as exc:  # noqa: BLE001 - 取得失敗の種類は問わず skip
        pytest.skip(f"Sudachi dictionary unavailable: {exc}")


@pytest.mark.slow
def test_sudachi_extracts_person(sudachi_extractor) -> None:
    entities = sudachi_extractor.extract("田中さんが東京で会議に参加した")
    names = [e["name"] for e in entities]
    assert any("田中" in n for n in names)


@pytest.mark.slow
def test_sudachi_extracts_location(sudachi_extractor) -> None:
    entities = sudachi_extractor.extract("田中さんが東京で会議に参加した")
    names = [e["name"] for e in entities]
    assert any("東京" in n for n in names)


def test_hybrid_fast_path_works() -> None:
    from nous.domain.memory.sudachi_extractor import HybridEntityExtractor

    extractor = HybridEntityExtractor()
    entities = extractor.extract_fast("田中さんが東京で会議に参加した")
    # regex fallback should at least extract the honorific name
    assert len(entities) >= 1
