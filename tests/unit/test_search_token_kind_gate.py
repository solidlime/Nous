"""item 5: dominantTokenKind 別 bm25 バー（FTS OR-fallback injection gate）.

- 純関数（classify_token_kind / bar_for_tokens / passes_bm25_bar）の境界
- SearchEngine の OR-fallback 経路だけに bar が効き、AND 経路は素通し
- 設定 default（SearchConfig.injection_max_bm25）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.config.settings import SearchConfig, Settings
from nous.domain.memory.entities import Memory
from nous.domain.search import engine as engine_mod
from nous.domain.search import token_kind_gate as gate
from nous.domain.search.engine import FTS_OR_FALLBACK_MIN, SearchEngine, SearchQuery
from nous.domain.search.token_kind_gate import (
    DEFAULT_INJECTION_MAX_BM25,
    KIND_BIGRAM,
    KIND_MIXED,
    KIND_WORD,
    bar_for_tokens,
    classify_token_kind,
    normalized_threshold,
    passes_bm25_bar,
)
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

# ---- 純関数 ----


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["量子", "テレポーテーション"], KIND_BIGRAM),  # CJK のみ
        (["hello", "world"], KIND_WORD),  # latin のみ
        (["量子", "hello", "world"], KIND_WORD),  # latin 優勢 (1 < 2)
        (["量子", "実験", "hello"], KIND_BIGRAM),  # CJK 優勢 (2 >= 1)
        (["量子", "hello"], KIND_BIGRAM),  # 同数は bigram (cjk >= lat)
        ([], KIND_MIXED),  # トークン無し
        (["!!", "123"], KIND_MIXED),  # CJK も latin も無し
        (["αβγ"], KIND_MIXED),  # 非 ASCII 非 CJK
    ],
)
def test_classify_token_kind(tokens, expected):
    assert classify_token_kind(tokens) == expected


def test_bar_for_tokens_bigram_and_word():
    bars = {"bigram": 2.0, "word": 2.5}
    assert bar_for_tokens(["量子"], bars) == 2.0
    assert bar_for_tokens(["hello"], bars) == 2.5


def test_bar_for_tokens_mixed_or_missing_is_none():
    bars = {"bigram": 2.0, "word": 2.0}
    assert bar_for_tokens([], bars) is None  # mixed はゲート無効
    assert bar_for_tokens(["量子"], {}) is None  # 未設定
    assert bar_for_tokens(["量子"], {"bigram": 0.0}) is None  # 非正値


def test_passes_bm25_bar_matches_negative_rank_rule():
    # raw bm25 rank = -(score/(1-score)) に戻して「rank <= -bar」と等価か確認。
    bar = 2.0
    th = normalized_threshold(bar)
    assert th == pytest.approx(2.0 / 3.0)
    assert passes_bm25_bar(th, bar)  # rank == -bar は通過（<=）
    assert not passes_bm25_bar(th - 1e-9, bar)
    assert passes_bm25_bar(0.9, bar)
    assert not passes_bm25_bar(0.5, bar)  # rank ≈ -1.0 > -2.0 は選外


def test_default_bars():
    assert DEFAULT_INJECTION_MAX_BM25 == {"bigram": 2.0, "word": 2.0}


# ---- 設定 ----


def test_search_config_default_injection_bar():
    assert SearchConfig().injection_max_bm25 == {"bigram": 2.0, "word": 2.0}


def test_settings_env_override_injection_bar(monkeypatch):
    monkeypatch.setenv("NOUS_SEARCH__INJECTION_MAX_BM25", '{"bigram": 3.5, "word": 4.0}')
    assert Settings().search.injection_max_bm25 == {"bigram": 3.5, "word": 4.0}


# ---- engine 経路 ----


def _mem(key: str, content: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


@pytest.fixture(autouse=True)
def _clear_query_cache():
    engine_mod._query_cache.clear()
    yield
    engine_mod._query_cache.clear()


@pytest.fixture(autouse=True)
def _stub_tokenizer(monkeypatch):
    """Sudachi 辞書ロードを避け、空白 split を決定的トークナイザにする。"""

    def fake(text: str) -> str:
        return " ".join(text.split())

    monkeypatch.setattr(engine_mod, "bar_for_tokens", gate.bar_for_tokens)
    from nous.infrastructure.sqlite import fts_tokenize

    monkeypatch.setattr(fts_tokenize, "tokenize_for_fts", fake)


class _FtsRepo:
    def __init__(self, and_pairs, or_pairs=()):
        self.calls: list[str] = []
        self._and = list(and_pairs)
        self._or = list(or_pairs)

    def search_fts(self, query, top_k=10, date_from=None, date_to=None, valid_at=None, tags=None, match_mode="and"):
        self.calls.append(match_mode)
        return Success(self._and if match_mode == "and" else self._or)


def _engine(repo: _FtsRepo, **kw) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success([])
    return SearchEngine(keyword_search=strat, memory_repo=repo, embedding_provider=lambda: None, **kw)


@pytest.mark.asyncio
async def test_or_fallback_drops_candidates_below_bar():
    # CJK クエリ → bigram バー 2.0 → 正規化閾値 0.667。0.5 は落ち、0.9 は残る。
    repo = _FtsRepo(
        and_pairs=[],
        or_pairs=[(_mem("noise", "確認のみ一致"), 0.5), (_mem("strong", "確認お願い"), 0.9)],
    )
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    assert result.is_ok
    assert repo.calls == ["and", "or"]
    assert {r.memory.key for r in result.value} == {"strong"}


@pytest.mark.asyncio
async def test_all_term_exact_survives_bar_via_boost():
    # 全語一致は boost 1.0 が先に立つので、生 bm25 が低くてもバーを通過する。
    repo = _FtsRepo(
        and_pairs=[],
        or_pairs=[(_mem("hit", "確認をお願いします"), 0.1), (_mem("weak", "確認のみ"), 0.1)],
    )
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    assert {r.memory.key for r in result.value} == {"hit"}


@pytest.mark.asyncio
async def test_and_path_not_gated():
    # AND プールが満杯（>= FTS_OR_FALLBACK_MIN）なら OR は走らず、低スコア AND 候補も残る。
    and_pairs = [(_mem(f"m{i}", f"確認{i}"), 0.1) for i in range(FTS_OR_FALLBACK_MIN)]
    repo = _FtsRepo(and_pairs)
    result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=10))
    assert repo.calls == ["and"]
    assert {r.memory.key for r in result.value} == {f"m{i}" for i in range(FTS_OR_FALLBACK_MIN)}


@pytest.mark.asyncio
async def test_mixed_query_disables_gate():
    # tokenize がトークンを返さない（mixed）→ バー無しで全候補通過。
    repo = _FtsRepo(and_pairs=[], or_pairs=[(_mem("noise", "確認のみ"), 0.05)])
    from nous.infrastructure.sqlite import fts_tokenize

    orig = fts_tokenize.tokenize_for_fts
    fts_tokenize.tokenize_for_fts = lambda _t: ""  # type: ignore[assignment]
    try:
        result = await _engine(repo).search(SearchQuery(text="確認 お願い", top_k=5))
    finally:
        fts_tokenize.tokenize_for_fts = orig  # type: ignore[assignment]
    assert "noise" in {r.memory.key for r in result.value}


@pytest.mark.asyncio
async def test_empty_bar_config_disables_gate():
    repo = _FtsRepo(and_pairs=[], or_pairs=[(_mem("noise", "確認のみ"), 0.05)])
    result = await _engine(repo, injection_max_bm25={}).search(SearchQuery(text="確認 お願い", top_k=5))
    assert "noise" in {r.memory.key for r in result.value}
