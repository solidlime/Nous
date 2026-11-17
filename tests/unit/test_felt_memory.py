"""backlog #40: 体験記憶の felt（その時の感情1語）— 正規化・タグ付与・検索ブースト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.memory_extractor import _save_extracted_facts
from nous.domain.memory.entities import Memory
from nous.domain.memory.felt import felt_match, felt_tag, felt_words, normalize_felt
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now

# ---------------------------------------------------------------------------
# 正規化
# ---------------------------------------------------------------------------


def test_normalize_felt_lowercases_and_strips_symbols():
    assert normalize_felt("  JOY！！ ") == "joy"
    assert normalize_felt("嬉しい。") == "嬉しい"
    assert normalize_felt("もやもや…") == "もやもや"


def test_normalize_felt_caps_length_at_20():
    assert normalize_felt("あ" * 30) == "あ" * 20


def test_normalize_felt_junk_is_empty():
    assert normalize_felt(None) == ""
    assert normalize_felt(1) == ""
    assert normalize_felt("!!!") == ""


def test_felt_tag_skips_empty():
    assert felt_tag(" 嬉しい ") == "felt:嬉しい"
    assert felt_tag("") is None
    assert felt_tag(None) is None


def test_felt_words_and_match():
    tags = ["preference", "felt:嬉しい", "felt:joy", "felt:"]
    assert felt_words(tags) == ["嬉しい", "joy"]
    assert felt_words(None) == []
    assert felt_match(tags, "あの日は嬉しかったね") is True
    assert felt_match(tags, "joy だった") is True
    # 1 文字の felt 語は誤爆するので一致に使わない
    assert felt_match(["felt:あ"], "あ") is False
    assert felt_match(tags, "") is False


# ---------------------------------------------------------------------------
# 保存時のタグ付与（facts）
# ---------------------------------------------------------------------------


async def _save_one(fact: dict) -> dict:
    ctx = MagicMock()
    ctx.search_engine.search = AsyncMock(return_value=Success([]))
    ctx.vector_store = None
    created: list[dict] = []

    async def fake_create(**kwargs):
        created.append(kwargs)
        mem = MagicMock()
        mem.key = "mem_new"
        mem.content = kwargs.get("content", "")
        return Success(mem)

    ctx.memory_service.create_memory = AsyncMock(side_effect=fake_create)
    await _save_extracted_facts(ctx, "p", [fact], "")
    return created[0]


async def test_fact_saves_felt_tag():
    saved = await _save_one({"content": "私は公園で転んだ", "tags": ["episodic"], "felt": " 恥ずかしい！"})

    assert "felt:恥ずかしい" in saved["tags"]
    assert "episodic" in saved["tags"]


async def test_fact_without_felt_has_no_felt_tag():
    saved = await _save_one({"content": "私は紅茶が好き", "tags": ["preference"], "felt": ""})

    assert not [t for t in saved["tags"] if t.startswith("felt:")]


# ---------------------------------------------------------------------------
# felt_boost（rank_policy）
# ---------------------------------------------------------------------------


_FIXED = get_now().replace(microsecond=0)  # recency の差で同点が崩れないよう固定


def _mem(key: str, content: str, tags: list[str] | None = None) -> Memory:
    return Memory(key=key, content=content, created_at=_FIXED, updated_at=_FIXED, importance=0.5, tags=tags or [])


@pytest.mark.asyncio
async def test_felt_boost_flips_tie_toward_felt_match():
    """同点の候補は、クエリの感情語が一致する felt タグを持つ方が上。"""
    felt = SearchResult(
        memory=_mem("felt", "公園の思い出", ["felt:恥ずかしい"]), score=0.0, source="semantic", cosine=0.5
    )
    plain = SearchResult(memory=_mem("plain", "公園の思い出"), score=0.0, source="semantic", cosine=0.5)
    query = SearchQuery(text="恥ずかしい思い出", top_k=5, rank_policy=RankPolicy())

    ranked = await SearchEngine(keyword_search=MagicMock())._apply_rank_policy([plain, felt], query)

    assert [r.memory.key for r in ranked] == ["felt", "plain"]
    assert ranked[0].score - ranked[1].score == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_felt_boost_zero_is_backward_compatible():
    felt = SearchResult(
        memory=_mem("felt", "公園の思い出", ["felt:恥ずかしい"]), score=0.0, source="semantic", cosine=0.5
    )
    plain = SearchResult(memory=_mem("plain", "公園の思い出"), score=0.0, source="semantic", cosine=0.5)
    query = SearchQuery(text="恥ずかしい思い出", top_k=5, rank_policy=RankPolicy(felt_boost=0.0))

    ranked = await SearchEngine(keyword_search=MagicMock())._apply_rank_policy([plain, felt], query)

    # 差は recency 計算の "now" の揺れのみ（felt_boost は 0.05 なので 1e-6 で区別できる）
    assert abs(ranked[0].score - ranked[1].score) < 1e-6
