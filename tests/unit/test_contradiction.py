"""Tests for ContradictionDetector."""

from __future__ import annotations

import pytest

from nous.domain.memory.contradiction import ContradictionDetector
from nous.domain.shared.errors import VectorStoreError
from nous.domain.shared.result import Failure, Success


class MockVectorStore:
    """Mock vector store for testing."""

    def __init__(self, results: list[tuple[str, float]] | None = None, error: bool = False):
        self._results = results or []
        self._error = error

    async def search(self, persona: str, query: str, limit: int = 10):
        if self._error:
            return Failure(VectorStoreError("Connection failed"))
        return Success(self._results)


class TestContradictionDetector:
    @pytest.mark.asyncio
    async def test_find_no_contradictions(self):
        """矛盾なし時は空リスト"""
        store = MockVectorStore(
            results=[
                ("mem_1", 0.3),
                ("mem_2", 0.5),
            ]
        )
        detector = ContradictionDetector(vector_store=store, threshold=0.85)
        result = await detector.find_potential_contradictions("test content", "persona1")
        assert result.is_ok
        report = result.value
        assert len(report.candidates) == 0
        assert report.threshold == 0.85

    @pytest.mark.asyncio
    async def test_find_potential_contradictions(self):
        """類似度が閾値以上の記憶が返される"""
        store = MockVectorStore(
            results=[
                ("mem_1", 0.90),
                ("mem_2", 0.87),
                ("mem_3", 0.60),
            ]
        )
        detector = ContradictionDetector(vector_store=store, threshold=0.85)
        result = await detector.find_potential_contradictions("test content", "persona1")
        assert result.is_ok
        report = result.value
        assert len(report.candidates) == 2
        assert report.candidates[0].memory_key == "mem_1"
        assert report.candidates[0].similarity == 0.90
        assert report.candidates[1].memory_key == "mem_2"
        assert report.candidates[1].similarity == 0.87

    @pytest.mark.asyncio
    async def test_exclude_self(self):
        """自分自身は除外される"""
        store = MockVectorStore(
            results=[
                ("mem_self", 0.99),
                ("mem_other", 0.90),
            ]
        )
        detector = ContradictionDetector(vector_store=store, threshold=0.85)
        result = await detector.find_potential_contradictions("test content", "persona1", exclude_key="mem_self")
        assert result.is_ok
        report = result.value
        assert len(report.candidates) == 1
        assert report.candidates[0].memory_key == "mem_other"

    @pytest.mark.asyncio
    async def test_threshold_filtering(self):
        """閾値未満の結果はフィルタされる"""
        store = MockVectorStore(
            results=[
                ("mem_1", 0.84),
                ("mem_2", 0.85),
                ("mem_3", 0.86),
            ]
        )
        detector = ContradictionDetector(vector_store=store, threshold=0.85)
        result = await detector.find_potential_contradictions("test", "persona1")
        assert result.is_ok
        report = result.value
        assert len(report.candidates) == 2  # 0.85 and 0.86
        keys = [c.memory_key for c in report.candidates]
        assert "mem_1" not in keys
        assert "mem_2" in keys
        assert "mem_3" in keys

    @pytest.mark.asyncio
    async def test_qdrant_unavailable_graceful(self):
        """Qdrant未接続時はgraceful degradation"""
        detector = ContradictionDetector(vector_store=None, threshold=0.85)
        result = await detector.find_potential_contradictions("test", "persona1")
        assert result.is_ok
        report = result.value
        assert len(report.candidates) == 0
        assert report.query_content == "test"

    @pytest.mark.asyncio
    async def test_vector_store_error_graceful(self):
        """ベクトルストアエラー時もgraceful degradation"""
        store = MockVectorStore(error=True)
        detector = ContradictionDetector(vector_store=store, threshold=0.85)
        result = await detector.find_potential_contradictions("test", "persona1")
        assert result.is_ok
        assert len(result.value.candidates) == 0

    @pytest.mark.asyncio
    async def test_custom_threshold(self):
        """カスタム閾値が正しく適用される"""
        store = MockVectorStore(
            results=[
                ("mem_1", 0.70),
                ("mem_2", 0.80),
            ]
        )
        detector = ContradictionDetector(vector_store=store, threshold=0.75)
        result = await detector.find_potential_contradictions("test", "persona1")
        assert result.is_ok
        assert len(result.value.candidates) == 1
        assert result.value.candidates[0].memory_key == "mem_2"

    def test_available_property(self):
        """availableプロパティの確認"""
        detector_with = ContradictionDetector(vector_store=MockVectorStore())
        assert detector_with.available is True

        detector_without = ContradictionDetector(vector_store=None)
        assert detector_without.available is False

    @pytest.mark.asyncio
    async def test_report_contains_query_content(self):
        """レポートにクエリコンテンツが含まれる"""
        store = MockVectorStore(results=[])
        detector = ContradictionDetector(vector_store=store)
        result = await detector.find_potential_contradictions("my query", "persona1")
        assert result.is_ok
        assert result.value.query_content == "my query"
