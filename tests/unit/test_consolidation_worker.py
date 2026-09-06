"""ConsolidationWorker gist contract tests (lane4).

- gist node shape: kind='semantic' / source_type='consolidated'（decay 除外述語が依存）
- summarizes relation: 元記憶 → gist ノード方向の memory_links（link_type='summarizes'）
- link 失敗は非致命（gist 保存は生き残る）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.workers.consolidation_worker import ConsolidationWorker
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


def _mem(key: str, kind: str = "semantic") -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=f"{key} のテスト記憶内容です。entity e1 について述べます。",
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind=kind,
        lifecycle_status="archived",
    )


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


class _BrokenEntityRepo:
    """get_entities_for_memories のみ実装（gist 化のグルーピング用）。upsert_link は常時 raise。"""

    def get_entities_for_memories(self, memory_keys, limit=50):
        return [{"memory_key": k, "id": "e1"} for k in memory_keys]

    def upsert_link(self, *args, **kwargs):
        raise RuntimeError("link boom")


def _consolidate(tmp_path, broken_link: bool = False):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_cw")
    conn.initialize_schema()
    try:
        repo = SQLiteMemoryRepository(conn)
        service = _FakeService(repo)
        for i in range(3):
            repo.save(_mem(f"src{i}"))
        # 全記憶が共有エンティティ e1 を持つ（クラスタリング成立条件）
        db = conn.get_memory_db()
        db.execute("INSERT OR IGNORE INTO entities (id, entity_type, first_seen, last_seen) VALUES ('e1', 'test', '', '')")
        db.executemany(
            "INSERT OR IGNORE INTO memory_entities (memory_key, entity_id, role) VALUES (?, 'e1', 'mentioned')",
            [(f"src{i}",) for i in range(3)],
        )
        db.commit()
        entity_repo = _BrokenEntityRepo() if broken_link else SQLiteEntityRepository(conn)
        ctx = SimpleNamespace(memory_repo=repo, memory_service=service, entity_repo=entity_repo)
        ConsolidationWorker(settings=MagicMock())._consolidate_persona(ctx, "test")
        return conn, repo, service
    except BaseException:
        conn.close()
        raise


class TestGistNodeShape:
    def test_gist_node_shape(self, tmp_path) -> None:
        """gist ノードは kind='semantic' / source_type='consolidated'（decay 除外述語の契約）。"""
        conn, repo, service = _consolidate(tmp_path)
        try:
            assert len(service.calls) == 1
            call = service.calls[0]
            assert call["kind"] == "semantic"
            assert call["source_type"] == "consolidated"
        finally:
            conn.close()


class TestSummarizesRelation:
    def test_gist_summarizes_relation(self, tmp_path) -> None:
        """元記憶 → gist ノード方向に link_type='summarizes' の memory_links が張られる。"""
        conn, repo, service = _consolidate(tmp_path)
        try:
            assert len(service.calls) == 1
            gist_key = service.calls[0] and "gist_1"
            rows = conn.get_memory_db().execute(
                "SELECT source_key, target_key FROM memory_links WHERE link_type = 'summarizes'"
            ).fetchall()
            assert {(r["source_key"], r["target_key"]) for r in rows} == {
                (f"src{i}", gist_key) for i in range(3)
            }
        finally:
            conn.close()

    def test_link_failure_is_nonfatal(self, tmp_path) -> None:
        """upsert_link が raise しても gist 生成は完了する（emit 規約: 失敗非致命）。"""
        conn, repo, service = _consolidate(tmp_path, broken_link=True)
        try:
            assert len(service.calls) == 1
            got = repo.find_by_key("gist_1")
            assert isinstance(got, Success) and got.value is not None
        finally:
            conn.close()


@pytest.mark.parametrize("rel_type", ["summarizes"])
def test_relation_type_validation(rel_type: str) -> None:
    """enricher が summarizes を有効 relation 型として受け付ける。"""
    from nous.infrastructure.llm.memory_enricher import _VALID_RELATION_TYPES

    assert rel_type in _VALID_RELATION_TYPES
