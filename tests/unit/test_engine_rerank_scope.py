"""rerank は deduped の上位のみを対象にする（CPU 環境での全件 encode 回避）。

回帰: 以前は deduped 全体（最大 80 件）を cross-encoder に渡しており、
1 リクエスト 9〜12 秒かかっていた。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str, content: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


def _engine(n: int = 30) -> tuple[SearchEngine, MagicMock]:
    strat = MagicMock()
    strat.search.return_value = Success([(_mem(f"m{i}", f"内容{i}"), 1.0 - i / 100) for i in range(n)])

    reranker = MagicMock()
    reranker.enabled = True
    reranker.is_loaded = True
    reranker.rerank.side_effect = lambda query, pairs, contents, top_k: list(pairs)

    engine = SearchEngine(keyword_search=strat, reranker=reranker, rerank_enabled=True, embedding_provider=lambda: None)
    return engine, reranker


@pytest.mark.asyncio
async def test_reranker_only_receives_top_candidates():
    engine, reranker = _engine()
    result = await engine.search(SearchQuery(text="内容", top_k=30))

    assert isinstance(result, Success)
    passed_pairs = reranker.rerank.call_args.args[1]
    assert [k for k, _ in passed_pairs] == [f"m{i}" for i in range(20)]
    # 対象外の要素も候補プールからは落ちない（top_k まで返る）
    assert {r.memory.key for r in result.value} == {f"m{i}" for i in range(30)}
