"""Tests for ContradictionDetector."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from nous.domain.memory.contradiction import (
    ContradictionDetector,
    ContradictionResult,
    ContradictionType,
    _parse_contradiction_response,
)
from nous.domain.memory.entities import Memory
from nous.domain.memory.evolution_service import MemoryEvolutionService
from nous.domain.search.engine import SearchResult
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


class TestParseContradictionResponse:
    def test_updated_fields_tags_are_stripped(self):
        """updated_fields に tags が含まれても除去され importance のみ残る"""
        text = json.dumps(
            {
                "type": "EXTENDABLE",
                "existing_key": "mem_1",
                "explanation": "テスト",
                "updated_fields": {"tags": ["last_reflection"], "importance": 0.8},
            }
        )
        result = _parse_contradiction_response(text)
        assert result is not None
        assert result.type == ContradictionType.EXTENDABLE
        assert result.updated_fields == {"importance": 0.8}

    def test_updated_fields_content_and_context_tags_are_stripped(self):
        """content / context_tags も除去される"""
        text = json.dumps(
            {
                "type": "EXTENDABLE",
                "existing_key": "mem_1",
                "explanation": "テスト",
                "updated_fields": {"content": "hacked", "context_tags": ["x"], "importance": 0.7},
            }
        )
        result = _parse_contradiction_response(text)
        assert result is not None
        assert result.updated_fields == {"importance": 0.7}

    def test_updated_fields_non_numeric_importance_is_dropped(self):
        """importance が文字列なら updated_fields ごと除去される"""
        text = json.dumps(
            {
                "type": "EXTENDABLE",
                "existing_key": "mem_1",
                "explanation": "テスト",
                "updated_fields": {"importance": "0.8"},
            }
        )
        result = _parse_contradiction_response(text)
        assert result is not None
        assert result.updated_fields is None


class FakeEvolutionRepo:
    """Minimal repo stub for evolution tests."""

    def __init__(self, memory: Memory):
        self._memory = memory
        self.update_calls: list[tuple[str, dict]] = []
        self.version_calls: list[dict] = []

    def find_by_key(self, key: str):
        return Success(self._memory)

    def get_latest_version_number(self, key: str):
        return Success(3)

    def save_version(self, memory_key, version, content, metadata, changed_by, change_type):
        self.version_calls.append(
            {
                "memory_key": memory_key,
                "version": version,
                "content": content,
                "metadata": metadata,
                "changed_by": changed_by,
                "change_type": change_type,
            }
        )
        return Success(None)

    def update(self, key: str, **kwargs):
        self.update_calls.append((key, kwargs))
        return Success(self._memory)


class FakeSearchEngine:
    """Minimal search engine stub for evolution tests."""

    def __init__(self, result):
        self._result = result

    async def search(self, query):
        return self._result


class FakeEnricher:
    """Stub enricher returning a fixed contradiction result."""

    def __init__(self, result: ContradictionResult):
        self._result = result

    def classify_contradiction(self, new_content: str, existing_memories: list[dict]):
        return self._result


class TestEvolutionExtendable:
    @pytest.mark.asyncio
    async def test_extendable_update_keeps_tags_and_records_version(self):
        """EXTENDABLE 適用時: tags/content は repo.update に渡らず、save_version が呼ばれる"""
        existing_memory = Memory(
            key="mem_existing",
            content="既存のプロジェクトに関する記憶。",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            importance=0.5,
            tags=["project:sample-project", "project_overview"],
            summary_ref="mem_summary",
        )
        repo = FakeEvolutionRepo(existing_memory)
        search_engine = FakeSearchEngine(
            Success(
                [
                    SearchResult(memory=existing_memory, score=0.9, source="semantic"),
                ]
            )
        )
        enricher = FakeEnricher(
            ContradictionResult(
                type=ContradictionType.EXTENDABLE,
                existing_memory_key="mem_existing",
                explanation="テスト",
                updated_fields={"importance": 0.9, "tags": ["last_reflection"], "content": "hacked"},
            )
        )
        service = MemoryEvolutionService(
            search_engine_ref=[search_engine],
            repo=repo,
            enricher=enricher,
            link_repo=None,
            contradiction_detector=None,
        )

        await service._evolve_related_memories(
            content="これは既存のプロジェクトについての新しい詳細情報を追加する記憶です。",
            new_memory_key="mem_new",
        )

        # EXTENDABLE の update に tags/content が渡らない
        importance_calls = [kwargs for key, kwargs in repo.update_calls if "importance" in kwargs]
        assert len(importance_calls) == 1
        assert importance_calls[0] == {"importance": 0.9}

        # version 記録が呼ばれている（更新前スナップショットに tags が保持）
        assert len(repo.version_calls) == 1
        version_call = repo.version_calls[0]
        assert version_call["memory_key"] == "mem_existing"
        assert version_call["version"] == 4
        assert version_call["changed_by"] == "evolution"
        assert version_call["change_type"] == "update"
        assert version_call["metadata"]["tags"] == ["project:sample-project", "project_overview"]
