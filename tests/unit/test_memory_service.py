"""Tests for MemoryService with an InMemory repository."""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from nous.domain.memory.enrichment import EnrichmentResult, RelationCandidate
from nous.domain.memory.service import MemoryService, _background_tasks
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory, MemoryStrength

TZ = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# InMemory implementations for testing
# ---------------------------------------------------------------------------


class InMemoryMemoryRepository:
    """Protocol-compatible in-memory repo for MemoryService tests."""

    def __init__(self) -> None:
        self._store: dict[str, Memory] = {}
        self._strengths: dict[str, MemoryStrength] = {}
        self._blocks: dict[str, dict] = {}

    def save(self, memory: Memory) -> Result[str, RepositoryError]:
        self._store[memory.key] = memory
        return Success(memory.key)

    def find_by_key(self, key: str) -> Result[Memory | None, RepositoryError]:
        return Success(self._store.get(key))

    def find_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]:
        memories = sorted(self._store.values(), key=lambda m: m.updated_at, reverse=True)
        return Success(memories[offset : offset + limit])

    def find_by_tags(self, tags: list[str], limit: int = 10) -> Result[list[Memory], RepositoryError]:
        tag_set = set(tags)
        result = [m for m in self._store.values() if set(m.tags) & tag_set]
        return Success(result[:limit])

    def update(self, key: str, **kwargs: Any) -> Result[Memory, RepositoryError]:
        if key not in self._store:
            return Failure(RepositoryError(f"Not found: {key}"))
        m = self._store[key]
        for field, value in kwargs.items():
            if hasattr(m, field):
                setattr(m, field, value)
        self._store[key] = m
        return Success(m)

    def delete(self, key: str) -> Result[None, RepositoryError]:
        self._store.pop(key, None)
        return Success(None)

    def tombstone(self, key: str) -> Result[None, RepositoryError]:
        if key not in self._store:
            return Failure(RepositoryError(f"Not found: {key}"))
        self._store[key].lifecycle_status = "tombstoned"
        return Success(None)

    def consume_memory(self, key: str) -> Result[None, RepositoryError]:
        mem = self._store.get(key)
        if mem is not None:
            from datetime import datetime

            mem.last_consumed_at = datetime.now(UTC)
        return Success(None)

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], RepositoryError]:
        tag_set = set(tags)
        results = []
        for m in self._store.values():
            if set(m.tags) & tag_set:
                if not include_consumed and m.last_consumed_at is not None:
                    continue
                results.append(m)
        return Success(results)

    def find_by_content_exact(self, content: str) -> Result[Memory | None, RepositoryError]:
        for m in self._store.values():
            if m.content.lower() == content.strip().lower():
                return Success(m)
        return Success(None)

    def count(self) -> Result[int, RepositoryError]:
        return Success(len(self._store))

    def search_keyword(self, query: str, limit: int = 10) -> Result[list[tuple[Memory, float]], RepositoryError]:
        results = []
        for m in self._store.values():
            if query.lower() in m.content.lower():
                results.append((m, 1.0))
        return Success(results[:limit])

    def find_all(self) -> Result[list[Memory], RepositoryError]:
        return Success(list(self._store.values()))

    def get_strength(self, key: str) -> Result[MemoryStrength | None, RepositoryError]:
        return Success(self._strengths.get(key))

    def save_strength(self, strength: MemoryStrength) -> Result[None, RepositoryError]:
        self._strengths[strength.memory_key] = strength
        return Success(None)

    def get_all_strengths(
        self,
    ) -> Result[list[MemoryStrength], RepositoryError]:
        return Success(list(self._strengths.values()))

    def get_block(self, block_name: str) -> Result[dict | None, RepositoryError]:
        return Success(self._blocks.get(block_name))

    def save_block(
        self,
        block_name: str,
        content: str,
        block_type: str = "custom",
        max_tokens: int = 500,
        priority: int = 0,
        metadata: dict | None = None,
    ) -> Result[None, RepositoryError]:
        self._blocks[block_name] = {
            "block_name": block_name,
            "content": content,
            "block_type": block_type,
            "max_tokens": max_tokens,
            "priority": priority,
            "metadata": metadata or {},
        }
        return Success(None)

    def list_blocks(self) -> Result[list[dict], RepositoryError]:
        return Success(list(self._blocks.values()))

    def delete_block(self, block_name: str) -> Result[None, RepositoryError]:
        self._blocks.pop(block_name, None)
        return Success(None)

    # Memory versions
    def save_version(
        self,
        memory_key: str,
        version: int,
        content: str,
        metadata: dict | None,
        changed_by: str,
        change_type: str,
    ) -> Result[None, RepositoryError]:
        if not hasattr(self, "_versions"):
            self._versions: dict[str, list[dict]] = {}
        if memory_key not in self._versions:
            self._versions[memory_key] = []
        self._versions[memory_key].append(
            {
                "memory_key": memory_key,
                "version": version,
                "content": content,
                "metadata": metadata,
                "changed_by": changed_by,
                "change_type": change_type,
                "created_at": "2025-01-01T00:00:00+09:00",
            }
        )
        return Success(None)

    def get_versions(self, memory_key: str) -> Result[list[dict], RepositoryError]:
        if not hasattr(self, "_versions"):
            self._versions: dict[str, list[dict]] = {}
        return Success(self._versions.get(memory_key, []))

    def get_version(self, memory_key: str, version: int) -> Result[dict | None, RepositoryError]:
        if not hasattr(self, "_versions"):
            self._versions: dict[str, list[dict]] = {}
        for v in self._versions.get(memory_key, []):
            if v["version"] == version:
                return Success(v)
        return Success(None)

    def get_latest_version_number(self, memory_key: str) -> Result[int, RepositoryError]:
        if not hasattr(self, "_versions"):
            self._versions: dict[str, list[dict]] = {}
        versions = self._versions.get(memory_key, [])
        if not versions:
            return Success(0)
        return Success(max(v["version"] for v in versions))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return InMemoryMemoryRepository()


@pytest.fixture
def service(repo):
    return MemoryService(repo)


@pytest.fixture
def service_factory():
    """Factory fixture to create MemoryService with optional enricher and entity_service."""

    def _create(repo, enricher=None, entity_service=None):
        return MemoryService(repo, entity_service=entity_service, enricher=enricher)

    return _create


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateMemory:
    async def test_create_success(self, service: MemoryService):
        result = await service.create_memory(content="Hello world", importance=0.7)
        assert result.is_ok
        memory = result.unwrap()
        assert memory.content == "Hello world"
        assert memory.importance == 0.7

    async def test_create_strips_whitespace(self, service: MemoryService):
        result = await service.create_memory(content="  spaced  ")
        assert result.is_ok
        assert result.unwrap().content == "spaced"

    async def test_create_empty_content_fails(self, service: MemoryService):
        result = await service.create_memory(content="")
        assert not result.is_ok

    async def test_create_whitespace_only_fails(self, service: MemoryService):
        result = await service.create_memory(content="   ")
        assert not result.is_ok

    async def test_create_with_tags(self, service: MemoryService):
        result = await service.create_memory(content="tagged", tags=["a", "b"])
        assert result.is_ok
        assert result.unwrap().tags == ["a", "b"]

    async def test_importance_clamped(self, service: MemoryService):
        r = await service.create_memory(content="high", importance=2.0)
        assert r.is_ok
        assert r.unwrap().importance == 1.0


class TestGetMemory:
    async def test_get_existing(self, service: MemoryService):
        created = (await service.create_memory(content="find me")).unwrap()
        result = service.get_memory(created.key)
        assert result.is_ok
        assert result.unwrap().content == "find me"

    async def test_get_nonexistent(self, service: MemoryService):
        result = service.get_memory("memory_99999999999999")
        assert not result.is_ok


class TestUpdateMemory:
    async def test_update_content(self, service: MemoryService):
        created = (await service.create_memory(content="original")).unwrap()
        result = service.update_memory(created.key, content="modified")
        assert result.is_ok
        assert result.unwrap().content == "modified"

    async def test_update_nonexistent(self, service: MemoryService):
        result = service.update_memory("memory_99999999999999", content="x")
        assert not result.is_ok


class TestDeleteMemory:
    async def test_delete_existing(self, service: MemoryService):
        created = (await service.create_memory(content="remove me")).unwrap()
        result = service.delete_memory(created.key)
        assert result.is_ok
        # Verify it's tombstoned (logical delete, not physical)
        # After deletion, get_memory should reject tombstoned memories
        get_result = service.get_memory(created.key)
        assert not get_result.is_ok
        # Repository can still find it for recovery
        repo_result = service._repo.find_by_key(created.key)
        assert repo_result.is_ok
        assert repo_result.unwrap().lifecycle_status == "tombstoned"

    async def test_delete_nonexistent(self, service: MemoryService):
        result = service.delete_memory("memory_99999999999999")
        assert not result.is_ok


class TestGetRecent:
    async def test_returns_most_recent(self, service: MemoryService):
        keys = []
        for i in range(5):
            with patch(
                "nous.domain.memory.write_service.generate_memory_key",
                return_value=f"memory_2025010100000{i}",
            ):
                r = await service.create_memory(content=f"memory {i}")
                assert r.is_ok
                keys.append(r.unwrap().key)
        result = service.get_recent(limit=3)
        assert result.is_ok
        assert len(result.unwrap()) == 3

    async def test_empty_repo(self, service: MemoryService):
        result = service.get_recent()
        assert result.is_ok
        assert result.unwrap() == []


class TestGetStats:
    def test_stats_empty(self, service: MemoryService):
        result = service.get_stats()
        assert result.is_ok
        stats = result.unwrap()
        assert stats["total_count"] == 0
        assert stats["tag_distribution"] == {}

    async def test_stats_with_data(self, service: MemoryService):
        with patch(
            "nous.domain.memory.write_service.generate_memory_key",
            return_value="memory_20250101000001",
        ):
            await service.create_memory(content="a", tags=["food"], emotion="joy")
        with patch(
            "nous.domain.memory.write_service.generate_memory_key",
            return_value="memory_20250101000002",
        ):
            await service.create_memory(content="b", tags=["food", "travel"], emotion="sadness")
        result = service.get_stats()
        assert result.is_ok
        stats = result.unwrap()
        assert stats["total_count"] == 2
        assert stats["tag_distribution"]["food"] == 2
        assert stats["tag_distribution"]["travel"] == 1
        assert stats["emotion_distribution"]["joy"] == 1
        assert stats["emotion_distribution"]["sadness"] == 1


class TestBoostRecall:
    async def test_boost_creates_strength_if_missing(self, service: MemoryService):
        created = (await service.create_memory(content="remember")).unwrap()
        result = service.boost_recall(created.key)
        assert result.is_ok
        strength = result.unwrap()
        assert strength.recall_count == 1
        assert strength.stability == 1.5

    async def test_boost_increments(self, service: MemoryService, repo: InMemoryMemoryRepository):
        created = (await service.create_memory(content="recall")).unwrap()
        service.boost_recall(created.key)
        result = service.boost_recall(created.key)
        assert result.is_ok
        assert result.unwrap().recall_count == 2

    # --- tests merged from test_boost_recall.py (direct MagicMock approach) ---

    def test_boost_recall_updates_strength(self) -> None:
        """boost_recall() が呼ばれると strength が更新される"""
        from nous.domain.memory.entities import MemoryStrength

        repo = MagicMock()
        existing_strength = MemoryStrength(memory_key="mem_001")
        repo.get_strength.return_value = MagicMock(is_ok=True, value=existing_strength)
        repo.save_strength.return_value = MagicMock(is_ok=True)

        from nous.domain.memory.service import MemoryService

        service = MemoryService(repo)
        result = service.boost_recall("mem_001")

        assert result.is_ok
        repo.save_strength.assert_called_once()

    def test_boost_recall_creates_new_strength_if_not_exists(self) -> None:
        """strength が存在しない場合は新規作成する"""
        repo = MagicMock()
        repo.get_strength.return_value = MagicMock(is_ok=True, value=None)
        repo.save_strength.return_value = MagicMock(is_ok=True)

        from nous.domain.memory.service import MemoryService

        service = MemoryService(repo)
        result = service.boost_recall("mem_new")

        assert result.is_ok
        repo.save_strength.assert_called_once()

    def test_boost_recall_returns_failure_on_repo_error(self) -> None:
        """リポジトリエラー時は Failure を返す"""
        repo = MagicMock()
        repo.get_strength.return_value = MagicMock(is_ok=False, error="DB error")

        from nous.domain.memory.service import MemoryService

        service = MemoryService(repo)
        result = service.boost_recall("mem_fail")

        assert not result.is_ok


class TestMemoryBlocks:
    def test_write_and_read_block(self, service: MemoryService):
        wr = service.write_block("test_block", "block content")
        assert wr.is_ok
        rd = service.read_block("test_block")
        assert rd.is_ok
        assert rd.unwrap()["content"] == "block content"

    def test_list_blocks(self, service: MemoryService):
        service.write_block("b1", "c1")
        service.write_block("b2", "c2")
        result = service.list_blocks()
        assert result.is_ok
        assert len(result.unwrap()) == 2

    def test_delete_block(self, service: MemoryService):
        service.write_block("del_block", "content")
        service.delete_block("del_block")
        result = service.read_block("del_block")
        assert result.is_ok
        assert result.unwrap() is None

    def test_write_empty_name_fails(self, service: MemoryService):
        result = service.write_block("", "content")
        assert not result.is_ok

    def test_write_empty_content_fails(self, service: MemoryService):
        result = service.write_block("name", "")
        assert not result.is_ok


class TestGetStatsTopN:
    async def test_top_n_truncates_tag_distribution(self, service):
        # 25個のユニークタグを持つメモリを作成
        for i in range(25):
            await service.create_memory(content=f"mem {i}", tags=[f"tag_{i:02d}"])

        result = service.get_stats(top_n=20)
        assert result.is_ok
        stats = result.unwrap()
        assert len(stats["tag_distribution"]) == 20
        assert "tag_distribution_note" in stats
        assert "5" in stats["tag_distribution_note"]

    async def test_top_n_custom_value(self, service):
        for i in range(5):
            await service.create_memory(content=f"mem {i}", tags=[f"tag_{i}"])

        result = service.get_stats(top_n=3)
        assert result.is_ok
        stats = result.unwrap()
        assert len(stats["tag_distribution"]) == 3
        assert "tag_distribution_note" in stats
        assert "2" in stats["tag_distribution_note"]

    async def test_top_n_no_note_when_within_limit(self, service):
        for i in range(3):
            await service.create_memory(content=f"mem {i}", tags=[f"tag_{i}"])

        result = service.get_stats(top_n=10)
        assert result.is_ok
        stats = result.unwrap()
        assert len(stats["tag_distribution"]) == 3
        assert "tag_distribution_note" not in stats

    async def test_top_n_truncates_emotion_distribution(self, service):
        # 22種の感情でメモリを作成（各1個）
        emotions = [
            "joy",
            "sadness",
            "anger",
            "fear",
            "surprise",
            "disgust",
            "love",
            "neutral",
            "anticipation",
            "trust",
            "anxiety",
            "excitement",
            "frustration",
            "nostalgia",
            "pride",
            "shame",
            "guilt",
            "loneliness",
            "contentment",
            "curiosity",
            "awe",
            "relief",
        ]
        for i, em in enumerate(emotions):
            await service.create_memory(content=f"mem_{i}", emotion=em)

        result = service.get_stats(top_n=10)
        assert result.is_ok
        stats = result.unwrap()
        assert len(stats["emotion_distribution"]) == 10
        assert "emotion_distribution_note" in stats
        assert "12" in stats["emotion_distribution_note"]


class TestTagValidation:
    async def test_create_too_many_tags_fails(self, service):
        tags = [f"tag{i}" for i in range(21)]
        result = await service.create_memory(content="too many tags", tags=tags)
        assert not result.is_ok

    async def test_create_exactly_20_tags_ok(self, service):
        tags = [f"tag{i}" for i in range(20)]
        result = await service.create_memory(content="max tags", tags=tags)
        assert result.is_ok
        assert len(result.unwrap().tags) == 20

    async def test_create_tag_too_long_fails(self, service):
        long_tag = "a" * 51
        result = await service.create_memory(content="long tag", tags=[long_tag])
        assert not result.is_ok

    async def test_create_tag_exactly_50_chars_ok(self, service):
        tag_50 = "a" * 50
        result = await service.create_memory(content="exact tag length", tags=[tag_50])
        assert result.is_ok

    async def test_update_too_many_tags_fails(self, service):
        created = (await service.create_memory(content="base memory")).unwrap()
        tags = [f"tag{i}" for i in range(21)]
        result = service.update_memory(created.key, tags=tags)
        assert not result.is_ok

    async def test_update_tag_too_long_fails(self, service):
        created = (await service.create_memory(content="base memory")).unwrap()
        long_tag = "b" * 51
        result = service.update_memory(created.key, tags=[long_tag])
        assert not result.is_ok

    async def test_create_project_tag_valid_slug_ok(self, service):
        result = await service.create_memory(content="proj tag", tags=["project:nous", "project:my-app"])
        assert result.is_ok

    async def test_create_project_tag_empty_slug_fails(self, service):
        result = await service.create_memory(content="proj tag", tags=["project:"])
        assert not result.is_ok

    async def test_create_project_tag_invalid_slug_fails(self, service):
        result = await service.create_memory(content="proj tag", tags=["project:Weird_Slug"])
        assert not result.is_ok

    async def test_create_project_tag_with_space_fails(self, service):
        result = await service.create_memory(content="proj tag", tags=["project:weird slug"])
        assert not result.is_ok

    async def test_create_plain_project_tag_ok(self, service):
        """'project' 単体（プレフィックス無し）は検証対象外。"""
        result = await service.create_memory(content="proj tag", tags=["project"])
        assert result.is_ok


class TestMemoryEnrichment:
    """Test that create_memory correctly interacts with the MemoryEnricher."""

    @staticmethod
    async def _drain_background_tasks() -> None:
        """Wait for all tracked background tasks (enrichment/evolution) to finish."""
        while _background_tasks:
            tasks = list(_background_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_skips_enrichment_when_importance_explicitly_set(self, repo, service_factory):
        """When importance != 0.5, enrichment should not be called."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock()
        svc = service_factory(repo, enricher=mock_enricher)

        await svc.create_memory(content="This is a meaningful memory about John.", importance=0.9)
        await self._drain_background_tasks()

        mock_enricher.enrich_async.assert_not_called()

    async def test_calls_enricher_when_importance_is_default_0_5(self, repo, service_factory):
        """When importance is default 0.5, enrichment should be called."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock(return_value=EnrichmentResult(importance=0.8, relations=[]))
        svc = service_factory(repo, enricher=mock_enricher)

        result = await svc.create_memory(content="This is a meaningful memory about John.")
        assert result.is_ok

        await self._drain_background_tasks()
        mock_enricher.enrich_async.assert_called_once()

    async def test_enricher_updates_importance_on_memory(self, repo, service_factory):
        """When enricher returns importance != 0.5, the memory importance is updated."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock(return_value=EnrichmentResult(importance=0.9, relations=[]))
        svc = service_factory(repo, enricher=mock_enricher)

        result = await svc.create_memory(content="This is an important memory.")
        assert result.is_ok
        memory = result.unwrap()

        await self._drain_background_tasks()
        assert memory.importance == 0.9

    async def test_enricher_does_not_override_explicit_importance(self, repo, service_factory):
        """When importance is explicitly set, enricher is not called."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock()
        svc = service_factory(repo, enricher=mock_enricher)

        result = await svc.create_memory(content="Memory with explicit importance", importance=0.3)
        assert result.is_ok
        memory = result.unwrap()

        await self._drain_background_tasks()
        assert memory.importance == 0.3
        mock_enricher.enrich_async.assert_not_called()

    async def test_enricher_failure_does_not_block_create(self, repo, service_factory):
        """When enricher raises an exception, memory creation still succeeds."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock(side_effect=RuntimeError("LLM down"))
        svc = service_factory(repo, enricher=mock_enricher)

        result = await svc.create_memory(content="This memory should still be created.")
        assert result.is_ok
        memory = result.unwrap()
        assert memory.content == "This memory should still be created."

        await self._drain_background_tasks()

    async def test_enrichment_does_not_block_create(self, repo, service_factory):
        """create_memory returns before enrichment completes (background task)."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_enrich(**kwargs):
            started.set()
            await release.wait()  # stays pending until we release it
            return EnrichmentResult(importance=0.9, relations=[])

        mock_enricher = MagicMock()
        mock_enricher.enrich_async = slow_enrich
        svc = service_factory(repo, enricher=mock_enricher)

        result = await svc.create_memory(content="This memory should return before enrichment finishes.")
        assert result.is_ok

        # create already returned; enrichment task is still blocked on `release`
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert not release.is_set(), "create returned while enrichment was still pending"

        # let the background task finish, then drain it
        release.set()
        await self._drain_background_tasks()

    async def test_enricher_relations_added_through_entity_service(self, repo, service_factory):
        """When enricher returns relations, entity_service.add_relation is called."""
        mock_enricher = MagicMock()
        mock_enricher.enrich_async = AsyncMock(
            return_value=EnrichmentResult(
                importance=0.7,
                relations=[
                    RelationCandidate(
                        source_entity="Alice",
                        target_entity="Bob",
                        relation_type="knows",
                        confidence=0.9,
                    )
                ],
            )
        )
        mock_entity_service = MagicMock()
        svc = service_factory(repo, enricher=mock_enricher, entity_service=mock_entity_service)

        result = await svc.create_memory(content="Alice knows Bob.")
        assert result.is_ok

        await self._drain_background_tasks()
        mock_entity_service.add_relation.assert_called_once_with(
            source="Alice",
            target="Bob",
            relation_type="knows",
            memory_key=result.unwrap().key,
            confidence=0.9,
        )
