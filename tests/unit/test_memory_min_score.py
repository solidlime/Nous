"""memory_min_score（低スコア記憶の切り捨て）の unit test。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.config.chat_config import ChatConfig
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=f"content-{key}", created_at=now, updated_at=now, importance=0.9)


def _ctx_with(scores: dict[str, float]) -> MagicMock:
    ctx = MagicMock()
    results = [SearchResult(memory=_mem(k), score=s, source="semantic") for k, s in scores.items()]
    ctx.search_engine.search = AsyncMock(return_value=Success(results))
    return ctx


async def _search(scores: dict[str, float], config: ChatConfig) -> list[str]:
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    _text, _dbg, mems = await _search_memories(
        _ctx_with(scores), "q", None, config, top_k=5, min_score=config.memory_min_score
    )
    return [m.key for m in mems]


def test_default_is_035():
    assert ChatConfig().memory_min_score == 0.35


@pytest.mark.asyncio
async def test_below_threshold_dropped():
    keys = await _search({"low": 0.2, "high": 0.8}, ChatConfig(memory_min_score=0.5))
    assert keys == ["high"]


@pytest.mark.asyncio
async def test_exactly_at_threshold_kept():
    keys = await _search({"edge": 0.5}, ChatConfig(memory_min_score=0.5))
    assert keys == ["edge"]


def test_missing_score_kept():
    """スコアを持たない記憶（None / 欠損）は後方互換のため残す。"""
    from nous.application.chat.pipeline.memory_retriever import _passes_min_score

    assert _passes_min_score(_mem("k"), 0.9) is True
    assert _passes_min_score({"content": "x"}, 0.9) is True
    assert _passes_min_score({"content": "x", "score": None}, 0.9) is True
