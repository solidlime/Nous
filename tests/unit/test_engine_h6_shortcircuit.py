"""H6 修正（案B）: rank_policy 指定時、entity boost / spreading activation は
score 加算を止め（composite で復活するため）、graph 信号の計算（entity_service /
link_repo）だけは _apply_rank_policy 内で行われる。reranker は score 置換型のため
rank_policy 経路では引き続き skip される。rank_policy=None の従来経路では
従来どおり 3 段全部が実行されることも併せて担保する。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str, content: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


def _engine_with_adjusters() -> tuple[SearchEngine, MagicMock, MagicMock, MagicMock]:
    """entity_service / reranker / link_repo を全部喋る engine を返す。"""
    strat = MagicMock()
    strat.search.return_value = Success([(_mem("m1", "内容1"), 0.9), (_mem("m2", "内容2"), 0.8)])

    entity_service = MagicMock()
    entity_service.extractor.extract.return_value = [("alice", 0.9)]
    entity_service.find_related_memories.return_value = Success(["m2"])

    reranker = MagicMock()
    reranker.enabled = True
    reranker.is_loaded = True
    reranker.rerank.return_value = [("m2", 9.9)]

    link_repo = MagicMock()
    link_repo.get_links_for_keys.return_value = {"m1": [{"target": "m2", "weight": 1.0}]}

    engine = SearchEngine(
        keyword_search=strat,
        entity_service=entity_service,
        reranker=reranker,
        rerank_enabled=True,
        link_repo=link_repo,
        embedding_provider=lambda: None,
    )
    return engine, entity_service, reranker, link_repo


@pytest.mark.asyncio
async def test_rank_policy_path_uses_graph_signal_and_skips_reranker():
    """rank_policy 経路: entity/PPR は graph 信号の計算に使われ（called）、
    置換型の reranker のみ skip される。"""
    engine, entity_service, reranker, link_repo = _engine_with_adjusters()
    result = await engine.search(SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    # graph 信号（entity match + PPR）は composite 統合のため計算される
    entity_service.extractor.extract.assert_called_once()
    entity_service.find_related_memories.assert_called_once()
    link_repo.get_links_for_keys.assert_called_once()
    # reranker は score 置換型のため rank_policy 経路では skip 継続
    reranker.rerank.assert_not_called()


@pytest.mark.asyncio
async def test_no_policy_path_still_runs_adjuster_steps():
    engine, entity_service, reranker, link_repo = _engine_with_adjusters()
    result = await engine.search(SearchQuery(text="alice の話", top_k=5))
    assert result.is_ok
    entity_service.extractor.extract.assert_called_once()
    reranker.rerank.assert_called_once()
    link_repo.get_links_for_keys.assert_called_once()


@pytest.mark.asyncio
async def test_rank_policy_results_still_sorted_by_composite():
    """skip 後も results は composite 順に返る（壊れていないことの最低担保）。"""
    engine, *_ = _engine_with_adjusters()
    result = await engine.search(SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    scores = [r.score for r in result.value]
    assert scores == sorted(scores, reverse=True)
