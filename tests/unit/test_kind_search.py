"""Tests for memory kind filter in SearchQuery and SearchEngine."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.shared.result import Success


def _mem(
    key: str,
    content: str = "content",
    kind: str = "semantic",
    importance: float = 0.5,
    emotion: str = "neutral",
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=importance,
        emotion=emotion,
        kind=kind,
    )


def _result(key: str, score: float, kind: str = "semantic", source: str = "keyword") -> SearchResult:
    return SearchResult(memory=_mem(key, kind=kind), score=score, source=source)


class TestSearchQueryKind:
    def test_kind_defaults_to_none(self) -> None:
        """SearchQuery.kind defaults to None (no filter)."""
        q = SearchQuery(text="test")
        assert q.kind is None

    def test_kind_can_be_set(self) -> None:
        q = SearchQuery(text="test", kind="episodic")
        assert q.kind == "episodic"


class TestFilterByKind:
    def test_none_kind_returns_all(self) -> None:
        results = [
            _result("k1", 1.0, kind="episodic"),
            _result("k2", 0.9, kind="semantic"),
        ]
        out = SearchEngine._filter_by_kind(results, None)
        assert len(out) == 2

    def test_matching_kind_kept(self) -> None:
        results = [
            _result("k1", 1.0, kind="episodic"),
            _result("k2", 0.9, kind="semantic"),
            _result("k3", 0.8, kind="procedural"),
        ]
        out = SearchEngine._filter_by_kind(results, "episodic")
        assert len(out) == 1
        assert out[0].memory.key == "k1"

    def test_no_match_returns_empty(self) -> None:
        results = [
            _result("k1", 1.0, kind="semantic"),
            _result("k2", 0.9, kind="procedural"),
        ]
        out = SearchEngine._filter_by_kind(results, "episodic")
        assert out == []

    def test_invalid_kind_returns_empty(self) -> None:
        """Invalid kind value matches nothing (Task 4: truthful filter)."""
        results = [
            _result("k1", 1.0, kind="episodic"),
            _result("k2", 0.9, kind="semantic"),
        ]
        out = SearchEngine._filter_by_kind(results, "bogus_kind")
        assert out == []


class TestSearchEngineKindIntegration:
    """Integration-style: SearchQuery.kind is threaded through search()."""

    @pytest.mark.asyncio
    async def test_keyword_mode_passes_kind(self) -> None:
        """kind filter applied as post-filter in keyword mode."""
        mems = [
            _mem("ep", kind="episodic"),
            _mem("sem", kind="semantic"),
        ]
        kw = MagicMock()
        kw.search.return_value = Success([(mem, 0.5) for mem in mems])
        engine = SearchEngine(keyword_search=kw)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", kind="episodic"))
        assert result.is_ok
        keys = {r.memory.key for r in result.value}
        assert keys == {"ep"}
        assert "sem" not in keys

    @pytest.mark.asyncio
    async def test_hybrid_mode_filters_by_kind(self) -> None:
        mem_ep = _mem("ep", kind="episodic")
        mem_sem = _mem("sem", kind="semantic")
        kw = MagicMock()
        kw.search.return_value = Success([(mem_ep, 0.7), (mem_sem, 0.6)])
        sem = AsyncMock()
        sem.search.return_value = Success([])
        engine = SearchEngine(keyword_search=kw, semantic_search=sem)
        result = await engine.search(SearchQuery(text="hello", mode="hybrid", kind="episodic"))
        assert result.is_ok
        keys = {r.memory.key for r in result.value}
        assert keys == {"ep"}
