"""audit H6: rank_policy 指定時は下流段（entity boost / reranker / spreading
activation）のスコア調整が _apply_rank_policy で破棄されるため、これらの段を
スキップする short-circuit の検証。rank_policy=None の従来経路では従来どおり
実行されることも併せて担保する。"""

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
        link_repo=link_repo,
        embedding_provider=lambda: None,
    )
    return engine, entity_service, reranker, link_repo


@pytest.mark.asyncio
async def test_rank_policy_path_skips_adjuster_steps():
    engine, entity_service, reranker, link_repo = _engine_with_adjusters()
    result = await engine.search(SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    # 全 adjuster 段が呼ばれない（composite 再計算で捨てられる計算を省略）
    entity_service.extractor.extract.assert_not_called()
    reranker.rerank.assert_not_called()
    link_repo.get_links_for_keys.assert_not_called()


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
