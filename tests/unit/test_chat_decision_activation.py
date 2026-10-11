"""Phase 14: chat 経路での Jev 判定ゲート有効化 (#011) の unit test。

対象:
- ``memory_retriever._search_memories`` が ``brain_decision_*`` 設定を
  ``SearchQuery`` に載せる（既定 off は従来どおり載せない）。
- ``decision_enabled=True`` + ``max_hops=1`` で gate が実際に動く。
- ``engine._emit_decision_bypass`` の warn が相関 ID 単位で集約される。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
from nous.domain.memory import wiring_events
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, invalidate_query_cache
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.decision_judge import JudgeVerdict


def _mem(key: str, content: str = "content") -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


class _StubJudge:
    def __init__(self, verdict: JudgeVerdict | None):
        self._verdict = verdict
        self.calls: list[tuple[str, list, str | None]] = []

    async def judge(self, query_text, candidates, model=None):
        self.calls.append((query_text, candidates, model))
        return self._verdict


def _repo(tmp_path, **cfg_kwargs):
    ChatConfigFileRepository(str(tmp_path)).save(ChatConfig(persona="p", **cfg_kwargs))

    class _Conn:
        data_dir = str(tmp_path)
        persona = "p"

    class _Repo:
        _conn = _Conn()

    return _Repo()


def _ctx_repo_authored_engine(mems, judge, repo):
    """keyword strategy を mems で固定した実 engine と、それを載せた ctx を返す。"""
    strat = MagicMock()
    strat.search.return_value = Success([(m, 0.9 - i * 0.1) for i, m in enumerate(mems)])
    engine = SearchEngine(keyword_search=strat, decision_judge=judge)
    ctx = MagicMock()
    ctx.search_engine = engine
    ctx.memory_repo = repo
    return ctx, engine


@pytest.fixture(autouse=True)
def _clean():
    invalidate_query_cache()
    wiring_events.clear()
    yield
    wiring_events.clear()


# ---------------------------------------------------------------------------
# (1) decision_enabled の接続
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_omits_decision_fields(tmp_path):
    """既定 off: SearchQuery に decision 系を一切載せない（現行挙動不変）。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = MagicMock()
    ctx.search_engine.search = AsyncMock(return_value=Success([]))
    ctx.memory_repo = _repo(tmp_path)  # 既定 off の config
    await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)

    query = ctx.search_engine.search.await_args.args[0]
    assert isinstance(query, SearchQuery)
    assert query.decision_enabled is False
    assert query.decision_model is None
    assert query.decision_threshold == 0.55
    assert query.max_hops == 1
    assert query.decision_time_weight == 0.0


@pytest.mark.asyncio
async def test_enabled_loads_config_values(tmp_path):
    """設定 on: model/threshold/max_hops/time_weight を config から載せる。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = MagicMock()
    ctx.search_engine.search = AsyncMock(return_value=Success([]))
    ctx.memory_repo = _repo(
        tmp_path,
        brain_decision_enabled=True,
        brain_decision_model="gpt-x",
        brain_decision_threshold=0.8,
        brain_decision_max_hops=3,
        brain_decision_time_weight=0.6,
    )
    await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)

    query = ctx.search_engine.search.await_args.args[0]
    assert query.decision_enabled is True
    assert query.decision_model == "gpt-x"
    assert query.decision_threshold == 0.8
    assert query.max_hops == 3
    assert query.decision_time_weight == 0.6


@pytest.mark.asyncio
async def test_enabled_hop1_activates_gate(tmp_path):
    """設定 on + max_hops=1（既定）でも chat 経路で gate が動く。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    judge = _StubJudge(JudgeVerdict(verdicts={"keep": 0.9, "drop": 0.1}, sufficiency=0.7))
    ctx, _engine = _ctx_repo_authored_engine(
        [_mem("keep"), _mem("drop")], judge, _repo(tmp_path, brain_decision_enabled=True)
    )
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)

    assert [m.key for m in mems] == ["keep"]
    assert len(judge.calls) == 1  # last_assistant 無し = 1 クエリ = judge 1 コール
    kinds = [e["kind"] for e in wiring_events.snapshot_after(0)]
    assert "decision_pass" in kinds
    assert "decision_reject" in kinds


@pytest.mark.asyncio
async def test_disabled_judge_not_called(tmp_path):
    """既定 off: 実 engine でも judge は呼ばれず全件返る（非破壊）。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    judge = _StubJudge(JudgeVerdict(verdicts={"a": 0.0, "b": 0.0}, sufficiency=0.0))
    ctx, _engine = _ctx_repo_authored_engine([_mem("a"), _mem("b")], judge, _repo(tmp_path))
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)

    assert [m.key for m in mems] == ["a", "b"]
    assert judge.calls == []


# ---------------------------------------------------------------------------
# (2) bypass warn の集約
# ---------------------------------------------------------------------------


def test_bypass_warn_aggregated_per_turn(caplog):
    """同一 turn の 2 クエリは warn 1 本。emit は毎回出て回数も追える。"""
    engine = SearchEngine(keyword_search=MagicMock())
    q1 = SearchQuery(text="hello", decision_enabled=True, turn_id="turn-x", request_id="req-1")
    q2 = replace(q1, request_id="req-2")

    with caplog.at_level(logging.WARNING, logger="nous.domain.search.engine"):
        engine._emit_decision_bypass("judge_unavailable", q1, 1)
        engine._emit_decision_bypass("judge_unavailable", q2, 1)

    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "decision gate bypassed" in r.getMessage()]
    assert len(warns) == 1
    bypass = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "decision_bypass"]
    assert [e["meta"]["bypass_count"] for e in bypass] == [1, 2]


def test_bypass_warn_first_per_turn(caplog):
    """turn が変われば初回は再び warning する（沈黙しない）。"""
    engine = SearchEngine(keyword_search=MagicMock())
    with caplog.at_level(logging.WARNING, logger="nous.domain.search.engine"):
        engine._emit_decision_bypass("no_candidates", SearchQuery(text="a", decision_enabled=True, turn_id="t-1"), 1)
        engine._emit_decision_bypass("no_candidates", SearchQuery(text="b", decision_enabled=True, turn_id="t-2"), 1)
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "decision gate bypassed" in r.getMessage()]
    assert len(warns) == 2


def test_bypass_warn_uncorrelated_still_warns(caplog):
    """相関 ID 無し（ad-hoc 経路）は集約せず毎回 warning する。"""
    engine = SearchEngine(keyword_search=MagicMock())
    with caplog.at_level(logging.WARNING, logger="nous.domain.search.engine"):
        for _ in range(3):
            engine._emit_decision_bypass("judge_unavailable", SearchQuery(text="a", decision_enabled=True), 1)
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "decision gate bypassed" in r.getMessage()]
    assert len(warns) == 3
