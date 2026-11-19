"""Settings.search.recency_lambda の伝播テスト（Phase 2 コンフィグ外部化 / fix-search）。

λ は time_utils.compute_recency_decay が呼び出し時に Settings から読む。
ここでは λ を変えると rank_policy 段の順位が入れ替わることを最小形で担保する。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from nous.config.settings import get_settings
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, invalidate_query_cache
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import compute_recency_decay, get_now

# 古いが重要（importance 0.6） vs 新しいが軽い（0.1）。λ 次第で勝者が入れ替わる。
_RECENCY_ONLY = RankPolicy(
    recency_weight=0.35,
    importance_weight=0.25,
    relevance_weight=0.0,
    lexical_weight=0.0,
    graph_boost_weight=0.0,
    emotion_salience_weight=0.0,
    felt_boost=0.0,
)


def _mem(key: str, importance: float, age_days: float, now: datetime) -> Memory:
    created = now - timedelta(days=age_days)
    return Memory(
        key=key, content=f"content {key}", created_at=created, updated_at=created, importance=importance, tags=[]
    )


def _engine(pairs: list[tuple[Memory, float]]) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    return SearchEngine(keyword_search=strat, embedding_provider=lambda: None)


async def _order(engine: SearchEngine, query: SearchQuery) -> list[str]:
    result = await engine.search(query)
    assert result.is_ok
    return [r.memory.key for r in result.value]


def _set_lambda(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    monkeypatch.setattr(get_settings().search, "recency_lambda", value)


def test_compute_recency_decay_reads_configured_lambda(monkeypatch: pytest.MonkeyPatch) -> None:
    old = get_now() - timedelta(days=10)
    _set_lambda(monkeypatch, 0.5)
    slow = compute_recency_decay(old)
    _set_lambda(monkeypatch, 1.0)
    fast = compute_recency_decay(old)
    assert slow == pytest.approx(compute_recency_decay(old, lambda_=0.5))
    assert fast < slow


def test_explicit_lambda_argument_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    old = get_now() - timedelta(days=1)
    _set_lambda(monkeypatch, 1.0)
    explicit = compute_recency_decay(old, lambda_=0.0)
    assert explicit == pytest.approx(1.0, abs=1e-9)


async def test_lambda_changes_rank_policy_order(monkeypatch: pytest.MonkeyPatch) -> None:
    now = get_now()
    pairs = [(_mem("old_important", 0.6, 20, now), 0.5), (_mem("new_light", 0.1, 2, now), 0.5)]

    _set_lambda(monkeypatch, 0.019)  # 減衰が緩い → importance が勝つ
    invalidate_query_cache()
    assert await _order(_engine(pairs), SearchQuery(text="q-slow", top_k=2, rank_policy=_RECENCY_ONLY)) == [
        "old_important",
        "new_light",
    ]

    _set_lambda(monkeypatch, 0.5)  # 減衰が急 → 新しさが勝つ
    invalidate_query_cache()
    assert await _order(_engine(pairs), SearchQuery(text="q-fast", top_k=2, rank_policy=_RECENCY_ONLY)) == [
        "new_light",
        "old_important",
    ]
