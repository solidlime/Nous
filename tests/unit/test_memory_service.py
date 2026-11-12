"""Tests for MemoryService with an InMemory repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from nous.domain.memory.service import MemoryService
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory

TZ = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# InMemory implementations for testing
# ---------------------------------------------------------------------------


class InMemoryMemoryRepository:
    """Protocol-compatible in-memory repo for MemoryService tests."""

    def __init__(self) -> None:
        self._store: dict[str, Memory] = {}
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

    def get_block(self, block_name: str, persona: str = "default") -> Result[dict | None, RepositoryError]:
        return Success(self._blocks.get(block_name))

    def save_block(
        self,
        block_name: str,
        content: str,
        block_type: str = "custom",
        max_tokens: int = 500,
        priority: int = 0,
        metadata: dict | None = None,
        persona: str = "default",
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

    def list_blocks(self, persona: str = "default") -> Result[list[dict], RepositoryError]:
        return Success(list(self._blocks.values()))

    def delete_block(self, block_name: str, persona: str = "default") -> Result[None, RepositoryError]:
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
        memory = result.value
        assert memory.content == "Hello world"
        assert memory.importance == 0.7

    async def test_create_strips_whitespace(self, service: MemoryService):
        result = await service.create_memory(content="  spaced  ")
        assert result.is_ok
        assert result.value.content == "spaced"

    async def test_create_empty_content_fails(self, service: MemoryService):
        result = await service.create_memory(content="")
        assert not result.is_ok

    async def test_create_whitespace_only_fails(self, service: MemoryService):
        result = await service.create_memory(content="   ")
        assert not result.is_ok

    async def test_create_with_tags(self, service: MemoryService):
        result = await service.create_memory(content="tagged", tags=["a", "b"])
        assert result.is_ok
        assert result.value.tags == ["a", "b"]

    async def test_importance_clamped(self, service: MemoryService):
        r = await service.create_memory(content="high", importance=2.0)
        assert r.is_ok
        assert r.value.importance == 1.0


class TestGetMemory:
    async def test_get_existing(self, service: MemoryService):
        created = (await service.create_memory(content="find me")).value
        result = service.get_memory(created.key)
        assert result.is_ok
        assert result.value.content == "find me"

    async def test_get_nonexistent(self, service: MemoryService):
        result = service.get_memory("memory_99999999999999")
        assert not result.is_ok


class TestUpdateMemory:
    async def test_update_content(self, service: MemoryService):
        created = (await service.create_memory(content="original")).value
        result = service.update_memory(created.key, content="modified")
        assert result.is_ok
        assert result.value.content == "modified"

    async def test_update_nonexistent(self, service: MemoryService):
        result = service.update_memory("memory_99999999999999", content="x")
        assert not result.is_ok


class TestDeleteMemory:
    async def test_delete_existing(self, service: MemoryService):
        created = (await service.create_memory(content="remove me")).value
        result = service.delete_memory(created.key)
        assert result.is_ok
        # Verify it's tombstoned (logical delete, not physical)
        # After deletion, get_memory should reject tombstoned memories
        get_result = service.get_memory(created.key)
        assert not get_result.is_ok
        # Repository can still find it for recovery
        repo_result = service._repo.find_by_key(created.key)
        assert repo_result.is_ok
        assert repo_result.value.lifecycle_status == "tombstoned"

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
                keys.append(r.value.key)
        result = service.get_recent(limit=3)
        assert result.is_ok
        assert len(result.value) == 3

    async def test_empty_repo(self, service: MemoryService):
        result = service.get_recent()
        assert result.is_ok
        assert result.value == []


class TestGetStats:
    def test_stats_empty(self, service: MemoryService):
        result = service.get_stats()
        assert result.is_ok
        stats = result.value
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
        stats = result.value
        assert stats["total_count"] == 2
        assert stats["tag_distribution"]["food"] == 2
        assert stats["tag_distribution"]["travel"] == 1
        assert stats["emotion_distribution"]["joy"] == 1
        assert stats["emotion_distribution"]["sadness"] == 1


class TestMemoryBlocks:
    def test_list_blocks(self, service: MemoryService):
        service.write_block("b1", "c1")
        service.write_block("b2", "c2")
        result = service.list_blocks()
        assert result.is_ok
        assert len(result.value) == 2

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
        stats = result.value
        assert len(stats["tag_distribution"]) == 20
        assert "tag_distribution_note" in stats
        assert "5" in stats["tag_distribution_note"]

    async def test_top_n_custom_value(self, service):
        for i in range(5):
            await service.create_memory(content=f"mem {i}", tags=[f"tag_{i}"])

        result = service.get_stats(top_n=3)
        assert result.is_ok
        stats = result.value
        assert len(stats["tag_distribution"]) == 3
        assert "tag_distribution_note" in stats
        assert "2" in stats["tag_distribution_note"]

    async def test_top_n_no_note_when_within_limit(self, service):
        for i in range(3):
            await service.create_memory(content=f"mem {i}", tags=[f"tag_{i}"])

        result = service.get_stats(top_n=10)
        assert result.is_ok
        stats = result.value
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
        stats = result.value
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
        assert len(result.value.tags) == 20

    async def test_create_tag_too_long_fails(self, service):
        long_tag = "a" * 51
        result = await service.create_memory(content="long tag", tags=[long_tag])
        assert not result.is_ok

    async def test_create_tag_exactly_50_chars_ok(self, service):
        tag_50 = "a" * 50
        result = await service.create_memory(content="exact tag length", tags=[tag_50])
        assert result.is_ok

    async def test_update_too_many_tags_fails(self, service):
        created = (await service.create_memory(content="base memory")).value
        tags = [f"tag{i}" for i in range(21)]
        result = service.update_memory(created.key, tags=tags)
        assert not result.is_ok

    async def test_update_tag_too_long_fails(self, service):
        created = (await service.create_memory(content="base memory")).value
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


class TestStateMemoryIsNotConsumed:
    """#52 回帰: 状態記憶は読んでも消費されない（次ターンも同じ状態が戻る）。

    旧実装は ``get_and_consume_one_shot`` が ``last_consumed_at`` を立てていたため、
    ``update_context`` が書いた状態は 1 ターンで消え、LLM が毎ターン書き直していた。
    """

    async def test_two_reads_return_same_state(self, service):
        created = await service.create_memory(content="physical_state: 眠い", tags=["physical_state"])
        assert created.is_ok

        first = service.get_by_tags(["physical_state"], include_consumed=True)
        second = service.get_by_tags(["physical_state"], include_consumed=True)

        assert first.is_ok and second.is_ok
        assert [m.key for m in first.value] == [m.key for m in second.value]
        assert len(first.value) == 1

    async def test_read_leaves_last_consumed_at_none(self, service):
        await service.create_memory(content="mental_state: 集中", tags=["mental_state"])
        read = service.get_by_tags(["mental_state"], include_consumed=True)
        assert read.is_ok
        assert read.value[0].last_consumed_at is None
