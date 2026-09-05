"""Two-layer CLS consolidation (F4) tests.

- episodic は生残存（gist 化しない・消さない）
- semantic 群から gist 生成（kind/source_type/derived_from 付与）
- valid_until 済み（無効）記憶は対象外
- 3 件未満で何もしない
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from nous.application.workers.consolidation_worker import ConsolidationWorker
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


def _mem(key: str, kind: str = "semantic", archived: bool = True, invalid: bool = False) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=f"{key} のテスト記憶内容です。 entity e1 について述べます。",
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind=kind,
        lifecycle_status="archived" if archived else "active",
        valid_from=now - timedelta(days=2),
        valid_until=(now - timedelta(days=1)) if invalid else None,
    )


class _FakeEntityRepo:
    def get_entities_for_memories(self, memory_keys, limit=50):
        return [{"memory_key": k, "id": "e1"} for k in memory_keys]


class _FakeService:
    """create_memory を repo 直書きで再現し、kwargs を記録する。"""

    def __init__(self, repo: SQLiteMemoryRepository):
        self._repo = repo
        self.calls: list[dict] = []

    async def create_memory(self, **kwargs):
        self.calls.append(kwargs)
        now = get_now()
        mem = Memory(
            key=f"gist_{len(self.calls)}",
            content=kwargs["content"],
            created_at=now,
            updated_at=now,
            importance=kwargs.get("importance", 0.5),
            kind=kwargs.get("kind", "semantic"),
            source_type=kwargs.get("source_type", "user_stated"),
            derived_from=kwargs.get("derived_from"),
            tags=kwargs.get("tags", []),
        )
        self._repo.save(mem)
        return Success(mem)


def _ctx(repo: SQLiteMemoryRepository, service: _FakeService):
    return SimpleNamespace(memory_repo=repo, memory_service=service, entity_repo=_FakeEntityRepo())


def _get(repo: SQLiteMemoryRepository, key: str) -> Memory:
    result = repo.find_by_key(key)
    assert isinstance(result, Success)
    assert result.value is not None
    return result.value


def _setup(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_cls")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    service = _FakeService(repo)
    return conn, repo, service


class TestCLSConsolidation:
    def test_episodic_kept_raw(self, tmp_path) -> None:
        """episodic のみ群 → gist なし・生残存"""
        conn, repo, service = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"ep{i}", kind="episodic"))
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(_ctx(repo, service), "test")
            assert service.calls == []
            for i in range(3):
                got = _get(repo, f"ep{i}")
                assert got.lifecycle_status == "archived"
                assert got.valid_until is None
        finally:
            conn.close()

    def test_semantic_gist_created(self, tmp_path) -> None:
        """semantic 3 件 → gist 1 件（kind/source_type/derived_from 付与、元は残る）"""
        conn, repo, service = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"sem{i}"))
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(_ctx(repo, service), "test")
            assert len(service.calls) == 1
            call = service.calls[0]
            assert call["kind"] == "semantic"
            assert call["source_type"] == "consolidated"
            assert sorted(json.loads(call["derived_from"])) == ["sem0", "sem1", "sem2"]
            for i in range(3):
                assert _get(repo, f"sem{i}") is not None
        finally:
            conn.close()

    def test_invalid_memories_excluded(self, tmp_path) -> None:
        """valid_until 済みは gist 対象外（derived_from にも入らない）"""
        conn, repo, service = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"ok{i}"))
            for i in range(2):
                repo.save(_mem(f"old{i}", invalid=True))
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(_ctx(repo, service), "test")
            assert len(service.calls) == 1
            assert sorted(json.loads(service.calls[0]["derived_from"])) == ["ok0", "ok1", "ok2"]
        finally:
            conn.close()

    def test_derived_from_chain(self, tmp_path) -> None:
        """derived_from と related_keys が源泉を示す"""
        conn, repo, service = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"src{i}"))
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(_ctx(repo, service), "test")
            call = service.calls[0]
            assert sorted(call["related_keys"]) == ["src0", "src1", "src2"]
            assert sorted(json.loads(call["derived_from"])) == sorted(call["related_keys"])
        finally:
            conn.close()

    def test_below_minimum_does_nothing(self, tmp_path) -> None:
        """2 件 (< 3) → 何もしない"""
        conn, repo, service = _setup(tmp_path)
        try:
            for i in range(2):
                repo.save(_mem(f"few{i}"))
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(_ctx(repo, service), "test")
            assert service.calls == []
        finally:
            conn.close()
