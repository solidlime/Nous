"""_apply_rank_policy の candidate re-encode 完全排除の検証。

relevance の取得経路は 2 系統のみで、候補側の encode は一切走らない:
  1. semantic 由来候補 — qdrant cosine（score）を SearchResult.cosine に carry（変更B/F1）
  2. keyword/fts 由来候補 — Qdrant から key 指定で stored vector を 1 バッチ取得し
     query vector との内積で relevance を計算（J4125 での候補 re-encode 数秒を排除）

Qdrant に存在しない key（SQLite のみの記憶）は cosine なし（relevance=0.0）。
encode へのフォールバックは設けない（レイテンシ再発防止）。
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

    def __init__(self, query_vec: np.ndarray) -> None:
        self.query_vec = query_vec
        self.calls: list[tuple[list[str], bool]] = []

    async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        self.calls.append((list(texts), is_query))
        return np.array([self.query_vec for _ in texts])

    @property
    def reencode_calls(self) -> list[list[str]]:
        return [texts for texts, is_query in self.calls if not is_query]

    @property
    def query_calls(self) -> list[list[str]]:
        return [texts for texts, is_query in self.calls if is_query]


class _RecordingRetriever:
    """key 指定 retrieve を話すフェイク。呼び出し（キー集合）を記録する。"""

    def __init__(self, key_vecs: dict[str, np.ndarray] | None = None, raise_error: Exception | None = None) -> None:
        self.key_vecs = key_vecs or {}
        self.raise_error = raise_error
        self.calls: list[list[str]] = []

    async def __call__(self, keys: list[str]) -> dict[str, np.ndarray]:
        self.calls.append(list(keys))
        if self.raise_error is not None:
            raise self.raise_error
        return {k: self.key_vecs[k] for k in keys if k in self.key_vecs}


def _engine(sem_pairs, keyword_pairs=(), encoder=None, retriever=None) -> SearchEngine:
    kw = MagicMock()
    kw.search.return_value = Success(list(keyword_pairs))
    sem = MagicMock()
    sem.search = AsyncMock(return_value=Success(list(sem_pairs)))
    return SearchEngine(
        keyword_search=kw,
        semantic_search=sem,
        embedding_provider=(lambda: encoder) if encoder is not None else (lambda: None),
        vector_retriever=retriever,
    )


@pytest.mark.asyncio
async def test_semantic_candidate_cosine_reused_without_reencode():
    """全候補が semantic 由来 → qdrant cosine を再利用し encode / retrieve は一切走らない。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    m2 = _mem("m2", "内容2", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever({"m1": np.array([1.0, 0.0])})
    engine = _engine([(m1, 0.9), (m2, 0.5)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert encoder.query_calls == []  # semantic cosine carry で query encode も不要
    assert retriever.calls == []
    by_key = {r.memory.key: r for r in result.value}
    assert by_key["m1"].cosine == pytest.approx(0.9, abs=1e-6)
    assert by_key["m2"].cosine == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_keyword_candidates_fetched_from_qdrant_without_reencode():
    """keyword 候補は Qdrant から key 指定で 1 バッチ取得。候補 encode は 0 回。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    m2 = _mem("m2", "内容2", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever(
        {"m1": np.array([0.5, 0.5]), "m2": np.array([-1.0, 0.0])},
    )
    engine = _engine([], keyword_pairs=[(m1, 0.9), (m2, 0.8)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.query_calls == [["q"]]
    assert encoder.reencode_calls == []  # 候補 encode は完全排除
    assert retriever.calls == [["m1", "m2"]]  # 1 バッチで全 key
    by_key = {r.memory.key: r for r in result.value}
    assert by_key["m1"].cosine == pytest.approx(0.5, abs=1e-6)
    assert by_key["m2"].cosine == pytest.approx(-1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_mixed_reuses_semantic_and_retrieves_keyword_only():
    """semantic 候補は cosine 再利用、retrieve は keyword 候補の key のみ。"""
    fixed = get_now()
    m_sem = _mem("sem", "semantic内容", created_at=fixed)
    m_kw = _mem("kw", "keyword内容", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever({"kw": np.array([0.2, 0.8])})
    engine = _engine([(m_sem, 0.7)], keyword_pairs=[(m_kw, 0.9)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert retriever.calls == [["kw"]]  # cosine 済みの semantic key は取得しない
    by_key = {r.memory.key: r for r in result.value}
    assert by_key["sem"].cosine == pytest.approx(0.7, abs=1e-6)
    assert by_key["kw"].cosine == pytest.approx(0.2, abs=1e-6)


@pytest.mark.asyncio
async def test_keys_missing_in_qdrant_get_zero_relevance_no_reencode():
    """Qdrant に無い key（SQLite のみ）→ cosine=0.0。encode フォールバックしない。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever({})  # 何もヒットしない
    engine = _engine([], keyword_pairs=[(m1, 0.9)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert result.value[0].cosine == 0.0


@pytest.mark.asyncio
async def test_retriever_failure_fails_open_with_zero_relevance():
    """retrieve 失敗 → fail-open（relevance=0.0 で rec/imp 順に継続）。"""
    fixed = get_now()
    m_hi = _mem("m1", "高重要", importance=0.9, created_at=fixed)
    m_lo = _mem("m2", "低重要", importance=0.2, created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever(raise_error=RuntimeError("qdrant down"))
    engine = _engine([], keyword_pairs=[(m_lo, 0.9), (m_hi, 0.5)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert [r.memory.key for r in result.value] == ["m1", "m2"]
    assert all(r.cosine == 0.0 for r in result.value)


@pytest.mark.asyncio
async def test_no_retriever_no_encoder_ranks_without_relevance():
    """retriever 無し・provider 無し → encode 完全 skip、rec/imp のみで順位付け。"""
    fixed = get_now()
    m_hi = _mem("m1", "高重要", importance=0.9, created_at=fixed)
    m_lo = _mem("m2", "低重要", importance=0.2, created_at=fixed)
    engine = _engine([], keyword_pairs=[(m_lo, 0.9), (m_hi, 0.5)])
    result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert [r.memory.key for r in result.value] == ["m1", "m2"]
    assert all(r.cosine == 0.0 for r in result.value)


@pytest.mark.asyncio
async def test_semantic_mode_also_reuses_cosine():
    """mode=semantic + rank_policy でも qdrant cosine を再利用する。"""
    fixed = get_now()
    m1 = _mem("m1", "内容1", created_at=fixed)
    encoder = _CountingEncoder(np.array([1.0, 0.0]))
    retriever = _RecordingRetriever()
    engine = _engine([(m1, 0.8)], encoder=encoder, retriever=retriever)
    result = await engine.search(SearchQuery(text="q", mode="semantic", top_k=5, rank_policy=RankPolicy()))
    assert result.is_ok
    assert encoder.reencode_calls == []
    assert result.value[0].cosine == pytest.approx(0.8, abs=1e-6)
