"""lexical 信号: rank_policy composite に語一致（keyword/fts）スコアを加算する検証。

① lexical_weight>0 で、語一致候補（lexical_score 高・cosine 低）が
   cosine 優勢候補（lexical_score None・cosine 高）を逆転する
② lexical_weight=0 は後方互換（lexical_score の有無が順位に影響しない）
③ dedup は同一 key の lexical_score を max 統合する
④ _to_search_results は keyword/fts のみ lexical_score を設定する
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult, _dedupe_keep_best
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from datetime import datetime

FIXED_QUERY = "機能確認テスト"


def _mem(key: str, content: str, importance: float = 0.5, created_at: datetime | None = None) -> Memory:
    now = created_at if created_at is not None else get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=importance)


def _engine() -> SearchEngine:
    return SearchEngine(keyword_search=MagicMock())


@pytest.mark.asyncio
async def test_lexical_weight_flips_word_match_over_cosine():
    """語一致候補が cosine 優勢候補を逆転する（lexical_weight>0）。"""
    fixed = get_now()
    lex = SearchResult(
        memory=_mem("lex", FIXED_QUERY, created_at=fixed),
        score=0.0,
        source="fts",
        cosine=0.3,
        lexical_score=1.0,
    )
    sem = SearchResult(
        memory=_mem("sem", "無関係な記憶", created_at=fixed),
        score=0.0,
        source="semantic",
        cosine=0.5,
        lexical_score=None,
    )
    query = SearchQuery(text=FIXED_QUERY, top_k=5, rank_policy=RankPolicy(lexical_weight=0.25))
    ranked = await _engine()._apply_rank_policy([sem, lex], query)
    assert [r.memory.key for r in ranked] == ["lex", "sem"]


@pytest.mark.asyncio
async def test_lexical_weight_zero_is_backward_compatible():
    """lexical_weight=0 では lexical_score が順位に影響しない。"""
    fixed = get_now()
    sem = SearchResult(
        memory=_mem("sem", "無関係な記憶", created_at=fixed),
        score=0.0,
        source="semantic",
        cosine=0.5,
    )
    lex = SearchResult(
        memory=_mem("lex", FIXED_QUERY, created_at=fixed),
        score=0.0,
        source="fts",
        cosine=0.3,
        lexical_score=1.0,
    )
    query = SearchQuery(text=FIXED_QUERY, top_k=5, rank_policy=RankPolicy(lexical_weight=0.0))
    ranked = await _engine()._apply_rank_policy([sem, lex], query)
    assert [r.memory.key for r in ranked] == ["sem", "lex"]


@pytest.mark.asyncio
async def test_none_lexical_score_unaffected_by_lexical_weight():
    """lexical_score=None（semantic 由来）の候補は lexical 項の影響を受けない。"""
    fixed = get_now()

    def _cand() -> SearchResult:
        return SearchResult(
            memory=_mem("sem", "無関係な記憶", created_at=fixed),
            score=0.0,
            source="semantic",
            cosine=0.5,
            lexical_score=None,
        )

    engine = _engine()
    with_lex = await engine._apply_rank_policy([_cand()], SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    without_lex = await engine._apply_rank_policy(
        [_cand()], SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(lexical_weight=0.0))
    )
    assert with_lex[0].score == pytest.approx(without_lex[0].score, abs=1e-9)


def test_dedupe_merges_lexical_score_by_max():
    """同一 key の lexical_score は max 統合され、スコア判定は変わらない。"""
    m = _mem("m", FIXED_QUERY)
    kw = SearchResult(memory=m, score=0.4, source="keyword", lexical_score=0.3)
    fts = SearchResult(memory=m, score=0.4, source="fts", lexical_score=0.9)
    out = _dedupe_keep_best([kw, fts])
    assert len(out) == 1
    assert out[0].score == pytest.approx(0.4)
    assert out[0].lexical_score == pytest.approx(0.9)

    # 高スコア側が lexical_score=None（semantic）でも低スコア側の値を引き継ぐ
    kw2 = SearchResult(memory=m, score=0.4, source="keyword", lexical_score=0.3)
    sem = SearchResult(memory=m, score=0.9, source="semantic", lexical_score=None)
    out2 = _dedupe_keep_best([sem, kw2])
    assert len(out2) == 1
    assert out2[0].source == "semantic"
    assert out2[0].lexical_score == pytest.approx(0.3)


def test_to_search_results_tags_lexical_only_for_keyword_fts():
    m = _mem("m", FIXED_QUERY)
    kw = SearchEngine._to_search_results([(m, 0.7)], "keyword")[0]
    fts = SearchEngine._to_search_results([(m, 0.8)], "fts")[0]
    sem = SearchEngine._to_search_results([(m, 0.9)], "semantic")[0]
    assert kw.lexical_score == pytest.approx(0.7)
    assert fts.lexical_score == pytest.approx(0.8)
    assert sem.lexical_score is None
