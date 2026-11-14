"""MoT high-confidence thoughts table (F5) tests.

- confidence≥0.8 のみ保存、低確信は破棄
- 想起は別枠 top-k=3、本想起スコアを汚さない
- corrosion＋TTL で消える
"""

from __future__ import annotations

from datetime import timedelta

import pytest

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


class _FakeKeyword:
    def __init__(self, memories: list[Memory]):
        self._memories = memories

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None, tags=None):
        return Success([(m, 0.5) for m in self._memories[:limit]])


def _thought_rows(conn: SQLiteConnection) -> list:
    return conn.get_memory_db().execute("SELECT * FROM mot_thoughts").fetchall()


class TestMotThoughts:
    def test_high_confidence_saved(self, tmp_path) -> None:
        """高確信 thought は保存される（閾値以上）"""
        conn, _repo = _setup(tmp_path)
        try:
            db = conn.get_memory_db()
            assert save_thought(db, "hi", "ck", "朝の飲み物についての考察", MOT_CONFIDENCE_THRESHOLD + 0.05) is True
            rows = _thought_rows(conn)
            assert len(rows) == 1
            assert rows[0]["consolidation_key"] == "ck"
            assert float(rows[0]["confidence"]) >= MOT_CONFIDENCE_THRESHOLD
        finally:
            conn.close()

    def test_low_confidence_dropped(self, tmp_path) -> None:
        """低確信は保存しない（閾値未満）"""
        conn, _repo = _setup(tmp_path)
        try:
            assert save_thought(conn.get_memory_db(), "lo", "ck", "trace", 0.6) is False
            assert _thought_rows(conn) == []
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
