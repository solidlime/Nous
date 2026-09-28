"""変更B: _apply_rank_policy の candidate 再 encode 排除の検証。

qdrant semantic 検索の score は Distance.COSINE の cosine そのものなので、
engine は SearchResult.cosine に carry し、rank_policy 段は再 encode せずに
その値で relevance を計算する。cosine を持たない候補（keyword/fts 由来）は
現行フォールバック（再 encode）を維持する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from datetime import datetime


def _mem(key: str, content: str, importance: float = 0.5, created_at: datetime | None = None) -> Memory:
    now = created_at if created_at is not None else get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=importance)


class _CountingEncoder:
    """async_encode_batch の呼び出し回数を記録するテスト用エンコーダ。"""

    def __init__(self, query_vec: np.ndarray, content_vecs: dict[str, np.ndarray] | None = None) -> None:
        self.query_vec = query_vec
        self.content_vecs = content_vecs or {}
        self.calls: list[tuple[list[str], bool]] = []

    async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        self.calls.append((list(texts), is_query))
        if is_query:
            return np.array([self.query_vec for _ in texts])
        return np.array([self.content_vecs.get(t, np.array([0.0, 1.0])) for t in texts])

    @property
    def reencode_calls(self) -> list[list[str]]:
        return [texts for texts, is_query in self.calls if not is_query]

    @property
    def query_calls(self) -> list[list[str]]:
        return [texts for texts, is_query in self.calls if is_query]


def _engine(sem_pairs, keyword_pairs=(), encoder=None) -> SearchEngine:
    kw = MagicMock()
    kw.search.return_value = Success(list(keyword_pairs))
    sem = MagicMock()
    sem.search = AsyncMock(return_value=Success(list(sem_pairs)))
    return SearchEngine(
        keyword_search=kw,
        semantic_search=sem,
        embedding_provider=(lambda: encoder) if encoder is not None else (lambda: None),
    )


@pytest.mark.asyncio
async def test_semantic_candidate_cosine_reused_without_reencode():
    """全候補が semantic 由来 → qdrant cosine を再利用し encode は一切走らない。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    m2 = _mem("m2", "内容2", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    engine = _engine([(m1, 0.9), (m2, 0.5)], encoder=encoder)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert encoder.query_calls == []
    by_key = {r.memory.key: r for r in result.value}
    assert by_key["m1"].cosine == pytest.approx(0.9, abs=1e-6)
    assert by_key["m2"].cosine == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_keyword_candidate_still_falls_back_to_reencode():
    """semantic 候補ゼロ（keyword のみ）→ 現行どおり再 encode フォールバック。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]), {"内容1": np.array([0.5, 0.5])})
    engine = _engine([], keyword_pairs=[(m1, 0.9)], encoder=encoder)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.query_calls == [["q"]]
    assert encoder.reencode_calls == [["内容1"]]
    assert result.value[0].cosine == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_mixed_reuses_semantic_and_reencodes_keyword_only():
    """semantic 候補は再利用、keyword 候補のみ再 encode に回る。"""
    fixed = get_now()
    m_sem = _mem("sem", "semantic内容", created_at=fixed)
    m_kw = _mem("kw", "keyword内容", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]), {"keyword内容": np.array([0.2, 0.8])})
    engine = _engine([(m_sem, 0.7)], keyword_pairs=[(m_kw, 0.9)], encoder=encoder)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    # semantic 候補の content は encode されない（keyword 候補だけ）
    assert encoder.reencode_calls == [["keyword内容"]]
    by_key = {r.memory.key: r for r in result.value}
    assert by_key["sem"].cosine == pytest.approx(0.7, abs=1e-6)
    assert by_key["kw"].cosine == pytest.approx(0.2, abs=1e-6)


@pytest.mark.asyncio
async def test_semantic_mode_also_reuses_cosine():
    """mode=semantic + rank_policy でも qdrant cosine を再利用する。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    engine = _engine([(m1, 0.8)], encoder=encoder)
    result = await engine.search(SearchQuery(text="q", mode="semantic", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert result.value[0].cosine == pytest.approx(0.8, abs=1e-6)
