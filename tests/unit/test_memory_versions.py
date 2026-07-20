"""Tests for memory versioning functionality."""

from __future__ import annotations

from typing import Any

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.memory.service import MemoryService
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

# ---------------------------------------------------------------------------
# InMemory repo with version support (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryVersionedRepository:
    """Protocol-compatible in-memory repo with version support."""

    def __init__(self) -> None:
        self._store: dict[str, Memory] = {}
        self._strengths: dict = {}
        self._blocks: dict = {}
        self._versions: dict[str, list[dict]] = {}

    def save(self, memory: Memory) -> Result[str, RepositoryError]:
        self._store[memory.key] = memory
        return Success(memory.key)

    def find_by_key(self, key: str) -> Result[Memory | None, RepositoryError]:
        return Success(self._store.get(key))

    def find_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]:
        memories = sorted(self._store.values(), key=lambda m: m.updated_at, reverse=True)
        return Success(memories[offset : offset + limit])

    def find_by_tags(self, tags: list[str], limit: int = 10) -> Result[list[Memory], RepositoryError]:
        return Success([])

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

    def count(self) -> Result[int, RepositoryError]:
        return Success(len(self._store))

    def search_keyword(self, query: str, limit: int = 10) -> Result[list[tuple[Memory, float]], RepositoryError]:
        return Success([])

    def find_all(self) -> Result[list[Memory], RepositoryError]:
        return Success(list(self._store.values()))

    def get_strength(self, key: str) -> Result[None, RepositoryError]:
        return Success(self._strengths.get(key))

    def save_strength(self, strength) -> Result[None, RepositoryError]:
        self._strengths[strength.memory_key] = strength
        return Success(None)

    def get_all_strengths(self) -> Result[list, RepositoryError]:
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
        self._blocks[block_name] = {"block_name": block_name, "content": content}
        return Success(None)

    def list_blocks(self) -> Result[list[dict], RepositoryError]:
        return Success(list(self._blocks.values()))

    def delete_block(self, block_name: str) -> Result[None, RepositoryError]:
        self._blocks.pop(block_name, None)
        return Success(None)

    # Version methods
    def save_version(
        self, memory_key: str, version: int, content: str, metadata: dict | None, changed_by: str, change_type: str
    ) -> Result[None, RepositoryError]:
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
        return Success(self._versions.get(memory_key, []))

    def get_version(self, memory_key: str, version: int) -> Result[dict | None, RepositoryError]:
        for v in self._versions.get(memory_key, []):
            if v["version"] == version:
                return Success(v)
        return Success(None)

    def get_latest_version_number(self, memory_key: str) -> Result[int, RepositoryError]:
        versions = self._versions.get(memory_key, [])
        if not versions:
            return Success(0)
        return Success(max(v["version"] for v in versions))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return InMemoryVersionedRepository()


@pytest.fixture
def service(repo):
    return MemoryService(repo)


@pytest.fixture
def sqlite_repo(sqlite_conn):
    return SQLiteMemoryRepository(sqlite_conn)


# ---------------------------------------------------------------------------
# Unit Tests: MemoryService versioning
# ---------------------------------------------------------------------------


class TestMemoryVersioning:
    def test_create_records_version_1(self, service: MemoryService, repo: InMemoryVersionedRepository):
        """作成時にversion 1が記録される"""
        result = service.create_memory(content="test memory")
        assert result.is_ok
        key = result.value.key
        versions = repo.get_versions(key).value
        assert len(versions) == 1
        assert versions[0]["version"] == 1
        assert versions[0]["change_type"] == "create"
        assert versions[0]["content"] == "test memory"
        assert versions[0]["changed_by"] == "user"

    def test_update_increments_version(self, service: MemoryService, repo: InMemoryVersionedRepository):
        """更新時にバージョンが増加する"""
        created = service.create_memory(content="original").unwrap()
        service.update_memory(created.key, content="modified")
        versions = repo.get_versions(created.key).value
        assert len(versions) == 2
        assert versions[0]["version"] == 1
        assert versions[0]["change_type"] == "create"
        assert versions[1]["version"] == 2
        assert versions[1]["change_type"] == "update"

    def test_delete_records_final_version(self, service: MemoryService, repo: InMemoryVersionedRepository):
        """削除時にdelete版が記録される"""
        created = service.create_memory(content="to delete").unwrap()
        service.delete_memory(created.key)
        versions = repo.get_versions(created.key).value
        assert len(versions) == 2
        assert versions[-1]["change_type"] == "delete"

    def test_get_history(self, service: MemoryService):
        """変更履歴が取得できる"""
        created = service.create_memory(content="history test").unwrap()
        service.update_memory(created.key, content="updated")
        result = service.get_memory_history(created.key)
        assert result.is_ok
        history = result.value
        assert len(history) == 2
        assert history[0]["change_type"] == "create"
        assert history[1]["change_type"] == "update"

    def test_version_metadata_contains_snapshot(self, service: MemoryService, repo: InMemoryVersionedRepository):
        """更新版のmetadataに変更前スナップショットが含まれる"""
        created = service.create_memory(content="original", importance=0.5).unwrap()
        service.update_memory(created.key, content="changed")
        versions = repo.get_versions(created.key).value
        update_version = versions[1]
        assert update_version["metadata"] is not None
        assert update_version["metadata"]["content"] == "original"
        assert update_version["metadata"]["importance"] == 0.5

    def test_multiple_updates_version_sequence(self, service: MemoryService, repo: InMemoryVersionedRepository):
        """複数回の更新でバージョン番号が正しくインクリメントされる"""
        created = service.create_memory(content="v1").unwrap()
        service.update_memory(created.key, content="v2")
        service.update_memory(created.key, content="v3")
        versions = repo.get_versions(created.key).value
        assert len(versions) == 3
        assert [v["version"] for v in versions] == [1, 2, 3]

    def test_version_persisted_in_sqlite(self, sqlite_repo: SQLiteMemoryRepository, sqlite_conn):
        """SQLiteに永続化される"""
        now = get_now()
        m = Memory(key="memory_test_ver", content="sqlite version test", created_at=now, updated_at=now)
        sqlite_repo.save(m)
        sqlite_repo.save_version(
            memory_key="memory_test_ver",
            version=1,
            content="sqlite version test",
            metadata=None,
            changed_by="user",
            change_type="create",
        )
        result = sqlite_repo.get_versions("memory_test_ver")
        assert result.is_ok
        versions = result.value
        assert len(versions) == 1
        assert versions[0]["memory_key"] == "memory_test_ver"
        assert versions[0]["version"] == 1
        assert versions[0]["change_type"] == "create"

    def test_get_specific_version(self, sqlite_repo: SQLiteMemoryRepository, sqlite_conn):
        """特定バージョンが取得できる"""
        sqlite_repo.save_version(
            memory_key="mem_specific",
            version=1,
            content="first",
            metadata=None,
            changed_by="user",
            change_type="create",
        )
        sqlite_repo.save_version(
            memory_key="mem_specific",
            version=2,
            content="second",
            metadata={"content": "first"},
            changed_by="user",
            change_type="update",
        )
        result = sqlite_repo.get_version("mem_specific", 2)
        assert result.is_ok
        v = result.value
        assert v is not None
        assert v["content"] == "second"
        assert v["version"] == 2

    def test_get_latest_version_number(self, sqlite_repo: SQLiteMemoryRepository, sqlite_conn):
        """最新バージョン番号の取得"""
        assert sqlite_repo.get_latest_version_number("nonexistent").value == 0
        sqlite_repo.save_version(
            memory_key="mem_latest",
            version=1,
            content="a",
            metadata=None,
            changed_by="user",
            change_type="create",
        )
        sqlite_repo.save_version(
            memory_key="mem_latest",
            version=2,
            content="b",
            metadata=None,
            changed_by="user",
            change_type="update",
        )
        assert sqlite_repo.get_latest_version_number("mem_latest").value == 2
