"""MoT high-confidence thoughts table (F5) tests.

- confidence≥0.8 のみ保存、低確信は破棄
- 想起は別枠 top-k=3、本想起スコアを汚さない
- corrosion＋TTL で消える
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.workers.consolidation_worker import ConsolidationWorker
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.mot_thoughts import (
    MOT_CONFIDENCE_THRESHOLD,
    fetch_thoughts,
    save_thought,
)


def _setup(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_mot")
    conn.initialize_schema()
    return conn, SQLiteMemoryRepository(conn)


def _mem(key: str, importance: float) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=f"{key} のテスト記憶内容です。 entity e1 について述べます。",
        created_at=now,
        updated_at=now,
        importance=importance,
        kind="semantic",
        lifecycle_status="archived",
        valid_from=now - timedelta(days=2),
    )


class _FakeEntityRepo:
    def get_entities_for_memories(self, memory_keys, limit=50):
        return [{"memory_key": k, "id": "e1"} for k in memory_keys]


class _FakeService:
    def __init__(self, repo: SQLiteMemoryRepository):
        self._repo = repo
        self.keys: list[str] = []

    async def create_memory(self, **kwargs):
        now = get_now()
        mem = Memory(
            key=f"gist_{len(self.keys)}",
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
        self.keys.append(mem.key)
        return Success(mem)


class _FakeKeyword:
    def __init__(self, memories: list[Memory]):
        self._memories = memories

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None, tags=None):
        return Success([(m, 0.5) for m in self._memories[:limit]])


def _thought_rows(conn: SQLiteConnection) -> list:
    return conn.get_memory_db().execute("SELECT * FROM mot_thoughts").fetchall()


class TestMotThoughts:
    def test_high_confidence_saved_via_consolidation(self, tmp_path) -> None:
        """高確信 gist → thoughts 行ができる"""
        conn, repo = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"hi{i}", 0.9))
            service = _FakeService(repo)
            ctx = SimpleNamespace(memory_repo=repo, memory_service=service, entity_repo=_FakeEntityRepo())
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(ctx, "test")
            rows = _thought_rows(conn)
            assert len(rows) == 1
            assert rows[0]["consolidation_key"] == service.keys[0]
            assert float(rows[0]["confidence"]) >= MOT_CONFIDENCE_THRESHOLD
        finally:
            conn.close()

    def test_low_confidence_dropped(self, tmp_path) -> None:
        """低確信は破棄（gist 自体は作られる）"""
        conn, repo = _setup(tmp_path)
        try:
            for i in range(3):
                repo.save(_mem(f"lo{i}", 0.6))
            service = _FakeService(repo)
            ctx = SimpleNamespace(memory_repo=repo, memory_service=service, entity_repo=_FakeEntityRepo())
            ConsolidationWorker(settings=MagicMock())._consolidate_persona(ctx, "test")
            assert len(service.keys) == 1
            assert _thought_rows(conn) == []
            assert save_thought(conn.get_memory_db(), "k", "ck", "trace", 0.6) is False
        finally:
            conn.close()

    def test_top_k_slot(self, tmp_path) -> None:
        """別枠 top-k=3"""
        conn, repo = _setup(tmp_path)
        try:
            db = conn.get_memory_db()
            for i in range(5):
                assert save_thought(db, f"t{i}", f"c{i}", f"朝の飲み物についての考察その{i}", 0.9) is True
            engine = SearchEngine(keyword_search=_FakeKeyword([]), memory_repo=repo)
            got = engine.fetch_mot_thoughts("朝の飲み物")
            assert len(got) == 3
            assert all("朝の飲み物" in t.trace for t in got)
        finally:
            conn.close()

    def test_ttl_and_corrosion(self, tmp_path) -> None:
        """TTL 切れは消去、corrosion で閾値割れは除外、新鮮な行は有効値そのまま"""
        conn, repo = _setup(tmp_path)
        try:
            db = conn.get_memory_db()
            now = get_now()
            old = format_iso(now - timedelta(hours=200))
            db.execute(
                "INSERT INTO mot_thoughts (key, consolidation_key, trace, confidence, created_at)"
                " VALUES ('old', 'ck', '朝の飲み物 古い考察', 0.95, ?)",
                (old,),
            )
            corroded_at = format_iso(now - timedelta(hours=30))
            db.execute(
                "INSERT INTO mot_thoughts (key, consolidation_key, trace, confidence, created_at)"
                " VALUES ('cor', 'ck', '朝の飲み物 腐食考察', 0.85, ?)",
                (corroded_at,),
            )
            save_thought(db, "fresh", "ck", "朝の飲み物 新鮮な考察", 0.9)
            got = fetch_thoughts(db, "朝の飲み物")
            keys = [t.key for t in got]
            assert "old" not in keys and "cor" not in keys
            assert keys == ["fresh"]
            assert got[0].confidence == pytest.approx(0.9)
            # TTL 切れ行は prune される
            assert [r["key"] for r in _thought_rows(conn)] == ["cor", "fresh"]
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_main_recall_unpolluted(self, tmp_path) -> None:
        """thoughts があっても本想起の結果・スコアは不変"""
        conn, repo = _setup(tmp_path)
        try:
            now = get_now()
            mems = [Memory(key=f"m{i}", content="朝の飲み物", created_at=now, updated_at=now) for i in range(2)]
            engine = SearchEngine(keyword_search=_FakeKeyword(mems), memory_repo=repo)
            before = await engine.search(SearchQuery(text="朝の飲み物", mode="keyword"))
            assert isinstance(before, Success)
            snapshot = [(r.memory.key, r.score) for r in before.value]
            save_thought(conn.get_memory_db(), "t0", "c0", "朝の飲み物についての考察", 0.95)
            after = await engine.search(SearchQuery(text="朝の飲み物", mode="keyword"))
            assert isinstance(after, Success)
            assert [(r.memory.key, r.score) for r in after.value] == snapshot
        finally:
            conn.close()
