"""Phase 13: 返答生成プロンプトに挿入された記憶の捕捉（prompt_inject）の unit test。

対象:
- ``wiring_events`` に ``prompt_inject`` / ``decision_hop`` kind が登録される。
- ``PromptBuildStep`` が挿入確定点で、実際に挿入した記憶 1 件 = 1 イベントを emit する
  （``source`` = key、``meta`` = persona/turn_id、``request_id`` は載せない）。
- ``PrepareStep`` の Episode fallback が文字列と構造化記録を一致させる。
- ``PostProcessStep`` の SSE ``retrieved`` が挿入集合のみになる（嘘を描かない）。
- バッファ枯渇時に decision 系 per-candidate が per-hop サマリへ畳まれ、連鎖の頭が消えない。
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.domain.memory import wiring_events
from nous.domain.shared.result import Success


@pytest.fixture(autouse=True)
def _clean_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


# ---------------------------------------------------------------------------
# (1) kind 登録
# ---------------------------------------------------------------------------


def test_new_kinds_registered() -> None:
    assert "prompt_inject" in wiring_events.WIRING_KINDS
    assert "decision_hop" in wiring_events.WIRING_KINDS
    assert wiring_events.emit("prompt_inject", source="m1", meta={"persona": "p", "turn_id": "t"}) is True


# ---------------------------------------------------------------------------
# (2) 挿入確定点での捕捉（PromptBuildStep）
# ---------------------------------------------------------------------------


def _run_prompt(turn_ctx: ChatTurnContext) -> None:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s"
    ctx.memory_service.get_profile_blocks.return_value = Success({})
    config = MagicMock()
    config.system_prompt = ""
    config.enabled_skills = []
    PromptBuildStep().run(ctx, config, turn_ctx)


def test_prompt_inject_emitted_per_inserted_memory() -> None:
    turn_ctx = ChatTurnContext(
        session_id="s",
        user_message="hi",
        turn_id="turn-1",
        related_memories="line-1\nline-2",
        memories_objects=[SimpleNamespace(key="m1"), SimpleNamespace(key="m2")],
        episodes_objects=[{"key": "episode:e1", "topic": "t", "summary": "s", "episode_id": "e1"}],
    )
    _run_prompt(turn_ctx)

    events = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "prompt_inject"]
    assert [e["source"] for e in events] == ["m1", "m2", "episode:e1"]
    assert [e["meta"]["origin"] for e in events] == ["note", "note", "episode"]
    for e in events:
        assert e["meta"]["persona"] == "herta"
        assert e["meta"]["turn_id"] == "turn-1"
        # 挿入は 2 クエリ + episode fallback の合成結果なので request_id 非依存。
        assert "request_id" not in e["meta"]


def test_prompt_inject_absent_when_no_memory_inserted() -> None:
    # context_section のみ（記憶挿入なし）では emit しない。
    turn_ctx = ChatTurnContext(
        session_id="s",
        user_message="hi",
        turn_id="turn-2",
        context_section="感情: 好奇心",
    )
    _run_prompt(turn_ctx)
    assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "prompt_inject"] == []


# ---------------------------------------------------------------------------
# (3) Episode の構造化追記（PrepareStep）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_records_episodes_structurally() -> None:
    from nous.application.chat.pipeline import prepare as prepare_mod
    from nous.application.chat.pipeline.prepare import PrepareStep
    from nous.domain.persona.entities import PersonaState

    async def _fake_search(_ctx, _user, _last, _config, **kwargs):
        return "note-line", {"results": []}, []

    async def _fake_episodes(_ctx, _query, top_k=3):
        return [
            {"topic": "t1", "summary": "s1", "content": "c1", "episode_id": "e1"},
            {"topic": "t2", "summary": "s2", "content": "c2", "episode_id": ""},
        ]

    state = PersonaState(persona="t")
    ctx = MagicMock()
    ctx.persona = "t"
    ctx.persona_service.get_context.return_value = Success(state)
    session = SimpleNamespace(pending_memory_task=None, _messages=[], _injected_memory_keys=set())
    config = SimpleNamespace(
        context_compression_mode="light",
        memory_preload_count=3,
        episode_search_enabled=True,
        show_message_timestamps=False,
        memory_digest_count=0,
    )
    turn_ctx = ChatTurnContext(session_id="s", user_message="hi", turn_id="turn-1")
    with (
        patch.object(prepare_mod, "_search_memories", _fake_search),
        patch.object(prepare_mod, "_build_context_section", AsyncMock(return_value="")),
        patch.object(prepare_mod, "_search_episodes", _fake_episodes),
        nullcontext(),
    ):
        await PrepareStep().run(ctx, session, turn_ctx, config)

    assert turn_ctx.related_memories.count("[Recent Episodes]") == 1
    assert [e["key"] for e in turn_ctx.episodes_objects] == ["episode:e1", "episode:t2"]
    # 文字列（related_memories）の episode 行数と構造化記録が一致する。
    episode_lines = [ln for ln in turn_ctx.related_memories.splitlines() if ln.startswith("  [")]
    assert len(episode_lines) == len(turn_ctx.episodes_objects) == 2


# ---------------------------------------------------------------------------
# (4) SSE retrieved を挿入集合に固定（PostProcessStep）
# ---------------------------------------------------------------------------


def test_retrieved_contains_only_inserted_memories() -> None:
    from nous.application.chat.pipeline.post import _inserted_retrieved

    tctx = ChatTurnContext(session_id="s", user_message="hi")
    tctx.memories_objects = [
        SimpleNamespace(key="a", content="ca"),
        SimpleNamespace(key="b", content="cb"),
    ]
    tctx.memories_raw = [
        {"content": "ca", "importance": 0.9, "score": 0.8, "cosine": 0.7},
        {"content": "noninserted", "importance": 0.5, "score": 0.6, "cosine": 0.5},
        {"content": "cb", "importance": 0.4, "score": 0.3, "cosine": 0.2},
    ]
    tctx.episodes_objects = [{"key": "episode:e1", "topic": "t", "summary": "es", "episode_id": "e1"}]

    out = _inserted_retrieved(tctx)
    assert [d["content"] for d in out] == ["ca", "cb", "es"]
    # 既存 shape（content/importance/score/cosine）を保つ。
    assert out[0]["score"] == 0.8
    assert out[0]["importance"] == 0.9


# ---------------------------------------------------------------------------
# (5) per-hop 集約
# ---------------------------------------------------------------------------


def test_decision_events_aggregate_under_pressure() -> None:
    cap = wiring_events.WIRING_BUFFER_SIZE
    for i in range(cap + 200):
        wiring_events.emit(
            "decision_pass",
            source=f"m{i}",
            weight=0.9,
            meta={"persona": "p", "request_id": "r1", "turn_id": "t1", "hop": 1, "jev": 0.9},
        )

    # 連鎖の頭が落ちていない（per-hop 集約で空きを作る）。
    assert wiring_events._dropped_from_head == 0
    hops = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "decision_hop"]
    assert hops, "expected per-hop decision summary"
    # 集約前の候補明細は復元できる。
    keys = {c["source"] for e in hops for c in e["meta"]["passed"]}
    assert "m0" in keys
    assert sum(e["meta"]["count"] for e in hops) > 0


def test_non_decision_flood_still_counts_drops() -> None:
    # 集約対象外（link_fire）は従来どおり頭から落ちて計器が進む。
    cap = wiring_events.WIRING_BUFFER_SIZE
    for i in range(cap + 3):
        wiring_events.emit("link_fire", source=f"s{i}")
    assert wiring_events._dropped_from_head == 3
