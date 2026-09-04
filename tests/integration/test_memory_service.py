"""Integration tests for MemoryService domain layer.

Tests the full lifecycle of memories, blocks, and search
using SQLite as the backing store (no Qdrant required).
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from nous.domain.memory.service import MemoryService
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="memorymcp_int_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def conn(tmp_dir):
    c = SQLiteConnection(tmp_dir, "test_persona")
    c.initialize_schema()
    return c


@pytest.fixture()
def repo(conn):
    return SQLiteMemoryRepository(conn)


@pytest.fixture()
def svc(repo):
    return MemoryService(repo)


@pytest.fixture()
async def seeded_svc(svc):
    """MemoryService with pre-seeded memories for search/filter tests."""
    seeds = [
        ("ユーザーはラーメンが好きです。毎日でも食べたい。", ["food", "preference"], "joy"),
        ("今日は宇宙の謎について研究した。ブラックホールの特性を調べている。", ["science", "research"], "curiosity"),
        ("大切な記憶：初めて望遠鏡で星を見た夜のこと。", ["memory", "stars"], "joy"),
        ("本日のメモ：実験データの整理が必要。優先度高い。", ["work", "memo"], "neutral"),
        ("友達とカフェでコーヒーを飲んだ。楽しかった。", ["social", "food"], "joy"),
    ]
    for content, tags, emotion in seeds:
        await svc.create_memory(content=content, tags=tags, emotion=emotion, importance=0.6)
    return svc


# ---------------------------------------------------------------------------
# C1: Memory CRUD full lifecycle
# ---------------------------------------------------------------------------


class TestMemoryCRUD:
    """Full create → read → update → delete lifecycle."""

    async def test_create_memory_returns_ok(self, svc):
        result = await svc.create_memory(content="テスト記憶です", importance=0.7)
        assert result.is_ok
        mem = result.value
        assert mem.key
        assert mem.content == "テスト記憶です"
        assert mem.importance == 0.7

    async def test_create_memory_normalizes_emotion(self, svc):
        result = await svc.create_memory(content="感情テスト", emotion="JOY")
        assert result.is_ok
        assert result.value.emotion == "joy"

    async def test_create_memory_empty_content_rejected(self, svc):
        result = await svc.create_memory(content="  ")
        assert not result.is_ok

    async def test_get_memory_by_key(self, svc):
        key = (await svc.create_memory(content="取得テスト")).value.key
        result = svc.get_memory(key)
        assert result.is_ok
        assert result.value.content == "取得テスト"

    async def test_get_memory_nonexistent(self, svc):
        result = svc.get_memory("nonexistent_key_xyz")
        assert not result.is_ok

    async def test_update_memory_content(self, svc):
        key = (await svc.create_memory(content="元のコンテンツ")).value.key
        result = svc.update_memory(key, content="更新後のコンテンツ")
        assert result.is_ok
        updated = svc.get_memory(key).value
        assert updated.content == "更新後のコンテンツ"

    async def test_update_memory_importance(self, svc):
        key = (await svc.create_memory(content="重要度テスト", importance=0.3)).value.key
        svc.update_memory(key, importance=0.9)
        assert svc.get_memory(key).value.importance == 0.9

    async def test_update_memory_tags(self, svc):
        key = (await svc.create_memory(content="タグテスト", tags=["old"])).value.key
        svc.update_memory(key, tags=["new", "updated"])
        assert svc.get_memory(key).value.tags == ["new", "updated"]

    async def test_delete_memory(self, svc):
        key = (await svc.create_memory(content="削除テスト")).value.key
        del_result = svc.delete_memory(key)
        assert del_result.is_ok
        # Verify tombstoned (logical delete) — get_memory excludes tombstoned
        get_result = svc.get_memory(key)
        assert not get_result.is_ok
        # Repository can still find for recovery
        repo_result = svc._repo.find_by_key(key)
        assert repo_result.is_ok
        assert repo_result.value.lifecycle_status == "tombstoned"

    async def test_delete_nonexistent_memory(self, svc):
        result = svc.delete_memory("does_not_exist")
        assert not result.is_ok

    async def test_get_recent(self, seeded_svc):
        result = seeded_svc.get_recent(limit=3)
        assert result.is_ok
        assert len(result.value) <= 3
        assert len(result.value) > 0

    async def test_get_stats(self, seeded_svc):
        result = seeded_svc.get_stats()
        assert result.is_ok
        stats = result.value
        assert stats.get("total_count", 0) >= 5

    async def test_create_with_all_fields(self, svc):
        result = await svc.create_memory(
            content="フルフィールドテスト",
            importance=0.85,
            emotion="curiosity",
            emotion_intensity=0.7,
            tags=["test", "full"],
            privacy_level="public",
            source_context="integration_test",
        )
        assert result.is_ok
        mem = result.value
        assert mem.importance == 0.85
        assert mem.emotion == "curiosity"
        assert mem.emotion_intensity == 0.7
        assert "test" in mem.tags
        assert mem.privacy_level == "public"
        assert mem.source_context == "integration_test"


# ---------------------------------------------------------------------------
# C2: Memory Block (write / read / list / delete)
# ---------------------------------------------------------------------------


class TestMemoryBlocks:
    """block_write / list_blocks / delete_block."""

    def test_write_block_overwrites_existing(self, svc):
        svc.write_block("overwrite_me", "初回コンテンツ")
        svc.write_block("overwrite_me", "上書きコンテンツ")
        result = svc.list_blocks()
        assert result.is_ok
        names = [b["block_name"] for b in result.value]
        assert "overwrite_me" in names

    def test_list_blocks_empty(self, svc):
        result = svc.list_blocks()
        assert result.is_ok
        assert isinstance(result.value, list)

    def test_list_blocks_returns_all(self, svc):
        svc.write_block("block_a", "コンテンツ A")
        svc.write_block("block_b", "コンテンツ B")
        svc.write_block("block_c", "コンテンツ C")
        result = svc.list_blocks()
        assert result.is_ok
        names = [b["block_name"] for b in result.value]
        assert "block_a" in names
        assert "block_b" in names
        assert "block_c" in names

    def test_delete_block(self, svc):
        svc.write_block("to_delete", "削除するブロック")
        del_result = svc.delete_block("to_delete")
        assert del_result.is_ok
        names = [b["block_name"] for b in svc.list_blocks().value]
        assert "to_delete" not in names

    def test_write_block_empty_name_rejected(self, svc):
        result = svc.write_block("  ", "コンテンツ")
        assert not result.is_ok

    def test_write_block_empty_content_rejected(self, svc):
        result = svc.write_block("valid_name", "")
        assert not result.is_ok


# ---------------------------------------------------------------------------
# C3: Search — keyword / hybrid (without Qdrant)
# ---------------------------------------------------------------------------


class _KeywordAdapter:
    """Thin adapter so SQLiteMemoryRepository fits the keyword strategy protocol."""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self._repo = repo

    def search(self, query: str, limit: int = 10, date_from=None, date_to=None, tags=None):
        return self._repo.search_keyword(query, limit, date_from=date_from, date_to=date_to, tags=tags)


class TestSearch:
    """Keyword and hybrid search via SearchEngine (no Qdrant needed)."""

    def test_keyword_search_finds_content(self, seeded_svc, repo):
        """Keyword search returns the memory that contains the query term."""
        result = repo.search_keyword("ラーメン", limit=5)
        assert result.is_ok
        contents = [m.content for m, _ in result.value]
        assert any("ラーメン" in c for c in contents)

    def test_keyword_search_japanese_multi_term(self, seeded_svc, repo):
        """多単語日本語検索でマッチする記憶が返る。"""
        result = repo.search_keyword("宇宙 ブラックホール", limit=5)
        assert result.is_ok
        assert len(result.value) >= 1

    def test_keyword_search_no_results(self, svc, repo):
        """存在しない単語ではヒットなし。"""
        result = repo.search_keyword("xyzzy_not_in_db_at_all_99999", limit=5)
        assert result.is_ok
        assert len(result.value) == 0

    async def test_search_engine_keyword_mode(self, seeded_svc, repo):
        """SearchEngine in keyword mode returns correct results."""
        adapter = _KeywordAdapter(repo)
        engine = SearchEngine(keyword_search=adapter)
        query = SearchQuery(text="記憶", mode="keyword", top_k=5)
        result = await engine.search(query)
        assert result.is_ok
        assert isinstance(result.value, list)

    async def test_search_engine_hybrid_falls_back_to_keyword(self, seeded_svc, repo):
        """Hybrid mode without Qdrant falls back gracefully to keyword."""
        adapter = _KeywordAdapter(repo)
        engine = SearchEngine(keyword_search=adapter, semantic_search=None)
        query = SearchQuery(text="食べ物", mode="hybrid", top_k=5)
        result = await engine.search(query)
        assert result.is_ok

    def test_find_all_returns_seeded_count(self, seeded_svc, repo):
        """find_all returns all 5 seeded memories."""
        result = repo.find_all()
        assert result.is_ok
        assert len(result.value) >= 5


# ---------------------------------------------------------------------------
# C4: Memory creation → version tracking
# ---------------------------------------------------------------------------


class TestMemoryVersioning:
    """Version 1 is recorded automatically on create."""

    async def test_create_records_version_1(self, svc, repo):
        key = (await svc.create_memory(content="バージョンテスト")).value.key
        history = svc.get_memory_history(key)
        assert history.is_ok
        versions = history.value
        assert len(versions) >= 1
        assert versions[0]["version"] == 1
        assert versions[0]["change_type"] == "create"

    def test_history_empty_for_unknown_key(self, svc):
        history = svc.get_memory_history("ghost_key")
        assert history.is_ok
        assert history.value == []
