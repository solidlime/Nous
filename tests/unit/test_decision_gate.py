"""Tests for the Jev 型判定ゲート + multi-hop search (#011)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.memory import wiring_events
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import (
    SearchEngine,
    SearchQuery,
    SearchResult,
    invalidate_query_cache,
)
from nous.domain.shared.result import Success
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent
from nous.infrastructure.llm.decision_judge import DecisionJudge, JudgeVerdict


def _mem(key: str, content: str = "content", tags: list[str] | None = None) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.5,
        emotion="neutral",
        tags=tags or [],
    )


def _result(key: str, score: float, content: str = "content", tags: list[str] | None = None) -> SearchResult:
    return SearchResult(memory=_mem(key, content=content, tags=tags), score=score, source="keyword")


def _make_keyword_strategy(pairs_by_text=None):
    """keyword strategy: text 毎に違う pairs を返せる（multi-hop 用）。"""
    strat = MagicMock()
    if pairs_by_text is None:
        strat.search.return_value = Success([])
    else:

        def _search(text, **kwargs):
            return Success(pairs_by_text.get(text, []))

        strat.search.side_effect = _search
    return strat


class _StubJudge:
    def __init__(self, verdict: JudgeVerdict | None):
        self._verdict = verdict
        self.calls: list[tuple[str, list, str | None]] = []

    async def judge(self, query_text, candidates, model=None):
        self.calls.append((query_text, candidates, model))
        return self._verdict


@pytest.fixture(autouse=True)
def _clean_events():
    invalidate_query_cache()
    wiring_events.clear()
    yield
    wiring_events.clear()


# ---------------------------------------------------------------------------
# decision gate
# ---------------------------------------------------------------------------


class TestDecisionGate:
    @pytest.mark.asyncio
    async def test_rejects_below_threshold(self):
        kw = _make_keyword_strategy({"hello": [(_mem("k1", "relevant"), 0.9), (_mem("k2", "noise"), 0.5)]})
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 0.9, "k2": 0.1}, sufficiency=0.7))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        query = SearchQuery(text="hello", mode="keyword", decision_enabled=True, decision_threshold=0.55)
        result = await engine.search(query)
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["k1"]
        kinds = [(e["kind"], e["source"]) for e in wiring_events.snapshot_after(0)]
        assert ("decision_pass", "k1") in kinds
        assert ("decision_reject", "k2") in kinds

    @pytest.mark.asyncio
    async def test_fail_open_when_judge_returns_none(self):
        kw = _make_keyword_strategy({"hello": [(_mem("k1"), 0.9), (_mem("k2"), 0.5)]})
        judge = _StubJudge(None)
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        result = await engine.search(SearchQuery(text="hello", mode="keyword", decision_enabled=True))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["k1", "k2"]
        assert wiring_events.snapshot_after(0) == []

    @pytest.mark.asyncio
    async def test_disabled_is_noop_and_judge_not_called(self):
        kw = _make_keyword_strategy({"hello": [(_mem("k1"), 0.9), (_mem("k2"), 0.5)]})
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 0.0, "k2": 0.0}, sufficiency=0.0))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        result = await engine.search(SearchQuery(text="hello", mode="keyword"))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["k1", "k2"]
        assert judge.calls == []

    @pytest.mark.asyncio
    async def test_model_override_passed_to_judge(self):
        kw = _make_keyword_strategy({"hello": [(_mem("k1"), 0.9)]})
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 1.0}, sufficiency=1.0))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        await engine.search(SearchQuery(text="hello", mode="keyword", decision_enabled=True, decision_model="gpt-x"))
        assert judge.calls[0][2] == "gpt-x"


# ---------------------------------------------------------------------------
# cache key
# ---------------------------------------------------------------------------


class TestCacheKey:
    def _key(self, engine, **overrides):
        query = SearchQuery(text="q", mode="hybrid", **overrides)
        return engine._query_cache_key(query, "hybrid")

    def test_decision_fields_included(self):
        engine = SearchEngine(keyword_search=_make_keyword_strategy())
        base = self._key(engine)
        assert self._key(engine, decision_enabled=True) != base
        assert self._key(engine, max_hops=3) != base
        assert self._key(engine, decision_threshold=0.9) != base
        assert self._key(engine, decision_model="m") != base

    def test_request_id_excluded(self):
        engine = SearchEngine(keyword_search=_make_keyword_strategy())
        assert self._key(engine, request_id="a") == self._key(engine, request_id="b")


# ---------------------------------------------------------------------------
# multi-hop
# ---------------------------------------------------------------------------


class TestMultiHop:
    @pytest.mark.asyncio
    async def test_sufficiency_stops_after_first_hop(self):
        kw = _make_keyword_strategy({"start": [(_mem("k1", "a"), 0.9)]})
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 1.0}, sufficiency=0.9))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        query = SearchQuery(text="start", mode="keyword", decision_enabled=True, max_hops=3, decision_threshold=0.55)
        result = await engine.search(query)
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["k1"]
        assert kw.search.call_count == 1
        stops = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "hop_stop"]
        assert stops[-1]["meta"]["reason"] == "sufficiency"
        assert stops[-1]["meta"]["hop"] == 1

    @pytest.mark.asyncio
    async def test_max_hops_stop_and_dedup(self):
        # hop 1 = "start", hop 2 = synthesized text; both return the same memory key.
        strat = MagicMock()
        strat.search.side_effect = lambda text, **kw: Success([(_mem("k1", "a"), 0.9)])
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 1.0}, sufficiency=0.1))
        engine = SearchEngine(keyword_search=strat, decision_judge=judge)
        query = SearchQuery(text="start", mode="keyword", decision_enabled=True, max_hops=2, decision_threshold=0.55)
        result = await engine.search(query)
        assert result.is_ok
        assert strat.search.call_count == 2
        starts = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "hop_start"]
        assert [e["meta"]["hop"] for e in starts] == [1, 2]
        stops = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "hop_stop"]
        assert stops[-1]["meta"]["reason"] == "max_hops"
        # キー重複排除により k1 は 1 件だけ。
        assert [r.memory.key for r in result.value] == ["k1"]

    @pytest.mark.asyncio
    async def test_no_candidates_stop(self):
        kw = _make_keyword_strategy()
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 1.0}, sufficiency=1.0))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        result = await engine.search(SearchQuery(text="start", mode="keyword", decision_enabled=True, max_hops=3))
        assert result.is_ok
        assert result.value == []
        stops = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "hop_stop"]
        assert stops[-1]["meta"]["reason"] == "no_candidates"

    @pytest.mark.asyncio
    async def test_max_hops_one_uses_single_path(self):
        kw = _make_keyword_strategy({"start": [(_mem("k1", "a"), 0.9)]})
        judge = _StubJudge(JudgeVerdict(verdicts={"k1": 1.0}, sufficiency=1.0))
        engine = SearchEngine(keyword_search=kw, decision_judge=judge)
        await engine.search(SearchQuery(text="start", mode="keyword", decision_enabled=True, max_hops=1))
        # hop イベントは出ない（現行経路）し、judge は通常の gate で 1 回だけ。
        events = wiring_events.snapshot_after(0)
        assert all(e["kind"] not in ("hop_start", "hop_stop") for e in events)
        assert len(judge.calls) == 1


class TestWiringKinds:
    def test_new_kinds_registered(self):
        assert {"decision_pass", "decision_reject", "hop_start", "hop_stop"} <= set(wiring_events.WIRING_KINDS)


# ---------------------------------------------------------------------------
# DecisionJudge parsing
# ---------------------------------------------------------------------------


class TestDecisionJudgeParse:
    def test_parse_valid(self):
        verdict = DecisionJudge._parse(
            json.dumps({"decisions": [{"index": 0, "probability": 0.9}], "sufficiency": 0.4}),
            [{"key": "a", "content": "x"}],
        )
        assert verdict is not None
        assert verdict.verdicts == {"a": 0.9}
        assert verdict.sufficiency == 0.4

    def test_parse_code_fence(self):
        text = '```json\n{"decisions": [{"index": 0, "probability": 0.2}], "sufficiency": 0.1}\n```'
        verdict = DecisionJudge._parse(text, [{"key": "a", "content": "x"}])
        assert verdict is not None
        assert verdict.verdicts == {"a": 0.2}

    def test_parse_invalid_json_returns_none(self):
        assert DecisionJudge._parse("not json", [{"key": "a"}]) is None

    def test_parse_no_valid_decisions_returns_none(self):
        assert DecisionJudge._parse('{"decisions": []}', [{"key": "a"}]) is None

    def test_parse_clamps_and_ignores_bad_index(self):
        text = json.dumps(
            {
                "decisions": [
                    {"index": 5, "probability": 0.9},
                    {"index": 0, "probability": 5.0},
                ],
                "sufficiency": 9,
            }
        )
        verdict = DecisionJudge._parse(text, [{"key": "a"}])
        assert verdict is not None
        assert verdict.verdicts == {"a": 1.0}
        assert verdict.sufficiency == 1.0

    def test_probability_missing_key_fails_open(self):
        verdict = JudgeVerdict(verdicts={"a": 0.0}, sufficiency=0.0)
        assert verdict.probability("unknown") == 1.0

    @pytest.mark.asyncio
    async def test_judge_calls_provider_and_parses(self):
        judge = DecisionJudge("openai", "key", "m")

        class _FakeProvider:
            def stream(self, **kwargs):
                async def _gen():
                    yield TextDeltaEvent(
                        content='{"decisions": [{"index": 0, "probability": 0.8}], "sufficiency": 0.5}'
                    )
                    yield DoneEvent()

                return _gen()

        judge._provider = lambda model=None: _FakeProvider()  # type: ignore[method-assign]
        verdict = await judge.judge("q", [{"key": "a", "content": "hello"}])
        assert verdict is not None
        assert verdict.verdicts == {"a": 0.8}

    @pytest.mark.asyncio
    async def test_judge_empty_inputs_returns_none(self):
        judge = DecisionJudge("openai", "key", "m")
        assert await judge.judge("", [{"key": "a"}]) is None
        assert await judge.judge("q", []) is None

    @pytest.mark.asyncio
    async def test_judge_provider_exception_returns_none(self):
        judge = DecisionJudge("openai", "key", "m")

        def _boom(model=None):
            raise RuntimeError("no provider")

        judge._provider = _boom  # type: ignore[method-assign]
        assert await judge.judge("q", [{"key": "a", "content": "x"}]) is None


class TestResolveDecisionJudge:
    def test_returns_none_without_conn(self):
        from nous.infrastructure.llm.decision_judge import resolve_decision_judge

        assert resolve_decision_judge(object()) is None
