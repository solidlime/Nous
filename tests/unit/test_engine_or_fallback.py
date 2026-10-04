"""FTS OR フォールバック（設計書 or_fallback_design.md §2d）の回帰テスト。

- AND プールが痩せた（< FTS_OR_FALLBACK_MIN）2語以上のときだけ OR を 1 回追加
- OR 結果の全語一致（raw content）文書は score 1.0 に boost
- AND/OR の同キーは dedup され RRF 二重計上しない
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search import engine as engine_mod
from nous.domain.search.engine import (
    FTS_OR_FALLBACK_MIN,
    SearchEngine,
    SearchQuery,
    _merge_fts_groups,
)
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str, content: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


@pytest.fixture(autouse=True)
def _clear_query_cache():
    engine_mod._query_cache.clear()
    yield
    engine_mod._query_cache.clear()


class _FtsRepo:
    """search_fts が match_mode で AND/OR を返す最小 fake。"""

    def __init__(self, and_pairs, or_pairs=()):
        self.calls: list[str] = []
        self._and = list(and_pairs)
        self._or = list(or_pairs)

    def search_fts(self, query, top_k=10, date_from=None, date_to=None, valid_at=None, tags=None, match_mode="and"):
        self.calls.append(match_mode)
        return Success(self._and if match_mode == "and" else self._or)


def _engine(repo: _FtsRepo) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success([])
    return SearchEngine(keyword_search=strat, memory_repo=repo, embedding_provider=lambda: None)


@pytest.mark.asyncio
async def test_or_fallback_fires_when_and_pool_thin():
    repo = _FtsRepo(
        and_pairs=[(_mem("m1", "確認しました"), 0.5)],
        or_pairs=[(_mem("m1", "確認しました"), 0.5), (_mem("m2", "確認をお願いします"), 0.3)],
    )
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    assert result.is_ok
    assert repo.calls == ["and", "or"]
    assert {r.memory.key for r in result.value} == {"m1", "m2"}


@pytest.mark.asyncio
async def test_no_fallback_when_and_pool_full():
    and_pairs = [(_mem(f"m{i}", f"確認{i}"), 0.5 - i / 10) for i in range(FTS_OR_FALLBACK_MIN)]
    repo = _FtsRepo(and_pairs)
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    assert result.is_ok
    assert repo.calls == ["and"]  # AND が生きている経路は不変


@pytest.mark.asyncio
async def test_no_fallback_for_single_term_query():
    repo = _FtsRepo([], [(_mem("m1", "確認"), 0.3)])
    result = await _engine(repo).search(SearchQuery(text="確認", top_k=5))
    assert result.is_ok
    assert repo.calls == ["and"]  # 1語は AND==OR なので追加探索しない


def test_merge_fts_groups_dedups_and_keeps_max():
    merged = _merge_fts_groups(
        and_results=[(_mem("a", "x"), 0.4)],
        or_results=[(_mem("a", "x"), 0.9), (_mem("b", "y"), 0.2)],
    )
    assert [m.key for m, _ in merged] == ["a", "b"]  # dedup + score 降順
    assert merged[0][1] == 0.9  # 高スコアを残す


@pytest.mark.asyncio
async def test_all_terms_bonus_boosts_to_one():
    repo = _FtsRepo(
        and_pairs=[],
        # 部分一致側の score は item 5 の OR-fallback bm25 バー（bigram 2.0）を
        # 通過する値にする（本テストは boost の検証であり、ゲートの検証ではない）。
        or_pairs=[(_mem("miss", "確認のみ"), 0.9), (_mem("hit", "確認をお願いします"), 0.1)],
    )
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    assert result.is_ok
    scores = {r.memory.key: r.score for r in result.value}
    assert scores["hit"] == 1.0  # 全語一致 → 正規化上限
    assert scores["miss"] == 0.9  # 部分一致は BM25 スコアのまま
    assert result.value[0].memory.key == "hit"  # boost で先頭


def test_sanitize_fts_query_or_join_keeps_quoting():
    """§2a: match_mode="or" は OR join。演算子語はクォートされ注入不可。"""
    from nous.infrastructure.sqlite.memory_search_repo import MemorySearchMixin

    q = MemorySearchMixin._sanitize_fts_query("確認 お願い", "or")
    assert " OR " in q and " AND " not in q
    for piece in q.split(" OR "):  # 各項は必ず引用符で保護される
        assert piece.startswith('"') and piece.endswith('"')
    assert MemorySearchMixin._sanitize_fts_query("OR", "or") == '"OR"'
