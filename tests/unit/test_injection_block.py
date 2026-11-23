"""注入ブロックの一本化 — chat 経路と API 経路が同一整形を通ることの unit test。

対象: nous/application/chat/pipeline/injection.py（レイアウトの唯一の定義）と、
その 2 つの消費者（PromptBuildStep / /api/search の _build_injection）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.injection import (
    RECALL_FOOTER,
    RETRIEVED_DATA_GUARD,
    build_injection_block,
    format_memory_lines,
    format_wiki_lines,
    state_to_raw,
)
from nous.domain.config.chat_config import ChatConfig
from nous.domain.shared.result import Success

PERSONA = "herta"


def _ctx(recent=()):
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx._session_event_repo = None
    ctx.memory_service.get_recent.return_value = Success(list(recent))
    return ctx


def _recent(content: str, key: str = "m1"):
    return SimpleNamespace(key=key, content=content, updated_at=datetime.now(UTC) - timedelta(hours=2))


def _config(**kwargs) -> ChatConfig:
    return ChatConfig(persona=PERSONA, system_prompt="あなたは{persona}その人", enabled_skills=[], **kwargs)


def _turn_ctx(**kwargs) -> ChatTurnContext:
    turn_ctx = ChatTurnContext(session_id="s", user_message="やあ", **kwargs)
    return turn_ctx


# ---------------------------------------------------------------------------
# 両経路の同一性
# ---------------------------------------------------------------------------


def test_chat_and_api_paths_produce_identical_block():
    """同一入力なら chat（PromptBuildStep）と API（build_injection_block）が同一文字列。"""
    from nous.application.chat.pipeline.prompt import PromptBuildStep

    ctx = _ctx([_recent("直近のできごと")])
    config = _config()
    time_context = "<time_context>\nNow: 2026-11-22 12:00\n</time_context>"
    state_raw = {"emotion": "joy", "emotion_intensity": 0.9}
    context_section = "感情: joy（強い）"
    memories = "（確か・最近）記憶1"

    turn_ctx = _turn_ctx()
    turn_ctx.time_context = time_context
    turn_ctx.state_raw = state_raw
    turn_ctx.context_section = context_section
    turn_ctx.related_memories = memories
    PromptBuildStep().run(ctx, config, turn_ctx)
    chat_block = turn_ctx.volatile_context

    api_block = build_injection_block(
        ctx,
        time_context=time_context,
        state_raw=state_raw,
        context_section=context_section,
        memories=memories,
        config=config,
    )

    assert chat_block == api_block
    assert chat_block.startswith("[NOUS CONTEXT]\n")
    assert chat_block.count("[NOUS CONTEXT]") == 1


def test_section_order_is_fixed():
    ctx = _ctx([_recent("直近のできごと")])
    block = build_injection_block(
        ctx,
        time_context="<time_context>Now</time_context>",
        state_raw={"emotion": "joy", "emotion_intensity": 0.9},
        context_section="感情: joy（強い）",
        memories="- 記憶1",
        them="\n【最近のやりとり】\n- 相手: やあ",
        active_skills="\n<active_skills>\n## search\n本文\n</active_skills>",
        wiki="1. (0.9) ページ [p1] 抜粋",
        config=_config(),
    )

    order = [
        "[NOUS CONTEXT]",
        "[最近のできごと",
        "【最近のやりとり】",
        "<active_skills>",
        "<time_context>",
        "【今の感情から】",
        "<retrieved_data>",
        RETRIEVED_DATA_GUARD,
        "<current_state>",
        "<related_memories>",
        "<related_wiki>",
        "</retrieved_data>",
        RECALL_FOOTER,
    ]
    positions = [block.index(token) for token in order]
    assert positions == sorted(positions)


def test_them_survives_right_after_header_plus_digest():
    """#41 の回帰防止: them はヘッダ／digest の直後（合成メッセージの途中に沈めない）。"""
    block = build_injection_block(
        _ctx([_recent("直近のできごと")]),
        time_context="",
        state_raw={},
        context_section="",
        memories="",
        them="\n【最近のやりとり】\n- 相手: やあ",
        config=_config(),
    )
    assert block.splitlines()[0] == "[NOUS CONTEXT]"
    assert block.splitlines()[1].startswith("[最近のできごと")
    assert "【最近のやりとり】" in block


# ---------------------------------------------------------------------------
# ガード・空入力
# ---------------------------------------------------------------------------


def test_guard_precedes_retrieved_sections_only():
    block = build_injection_block(
        _ctx(),
        time_context="",
        state_raw={},
        context_section="感情: joy（強い）",
        memories="",
        config=_config(),
    )
    head, rest = block.split("<retrieved_data>", 1)
    assert RETRIEVED_DATA_GUARD not in head
    assert rest.split("</retrieved_data>", 1)[0].lstrip().startswith(RETRIEVED_DATA_GUARD.splitlines()[0])
    assert RETRIEVED_DATA_GUARD in block


def test_empty_memories_omits_tag_and_footer_follows_retrieved_data():
    block = build_injection_block(
        _ctx(),
        time_context="",
        state_raw={},
        context_section="感情: joy（強い）",
        memories="",
        config=_config(),
    )
    assert "<related_memories>" not in block
    assert "<related_wiki>" not in block
    assert block.rstrip().endswith(RECALL_FOOTER)


def test_all_empty_returns_empty_string():
    assert (
        build_injection_block(_ctx(), time_context="", state_raw={}, context_section="", memories="", config=_config())
        == ""
    )
    # config / state_raw 未指定（None）でも getattr 経路で落ちない
    assert build_injection_block(_ctx(), time_context="", state_raw={}, context_section="", memories="") == ""


# ---------------------------------------------------------------------------
# chat 専用分（them / active_skills）が pi 経路に混ざらない
# ---------------------------------------------------------------------------


def test_chat_only_sections_absent_from_api_block():
    """pi 経路（them/active_skills を渡さない）には chat 専用分が入らない。"""
    api_block = build_injection_block(
        _ctx(),
        time_context="<time_context>Now</time_context>",
        state_raw={},
        context_section="感情: joy（強い）",
        memories="- 記憶1",
        wiki="1. (0.9) ページ [p1] 抜粋",
        config=_config(),
    )
    assert "【最近のやりとり】" not in api_block
    assert "<active_skills>" not in api_block
    # pi 側の wiki は載る / chat は wiki を渡さないので載らない
    assert "<related_wiki>" in api_block
    chat_block = build_injection_block(
        _ctx(),
        time_context="<time_context>Now</time_context>",
        state_raw={},
        context_section="感情: joy（強い）",
        memories="- 記憶1",
        config=_config(),
    )
    assert "<related_wiki>" not in chat_block


# ---------------------------------------------------------------------------
# 部品
# ---------------------------------------------------------------------------


def test_state_to_raw_stringifies_non_scalars():
    state = SimpleNamespace(persona="herta", intensity=0.4, tags=["a"], extra=object())
    raw = state_to_raw(state)
    assert raw["persona"] == "herta"
    assert raw["intensity"] == 0.4
    assert raw["tags"] == ["a"]
    assert isinstance(raw["extra"], str)


def test_state_to_raw_handles_object_without_dict():
    assert state_to_raw(SimpleNamespace(__dict__=None) if False else 42) == {}


def test_format_memory_lines_annotates_and_records_injected_keys():
    memory = SimpleNamespace(
        key="k1",
        content="記憶の本文",
        confidence=1.0,
        created_at=datetime.now(UTC) - timedelta(hours=1),
        source_type="user_stated",
        kind="semantic",
    )
    injected: set[str] = set()
    text, memories = format_memory_lines([SimpleNamespace(memory=memory, score=1.0)], injected_keys=injected)

    assert text == "（確か・最近） 記憶の本文"
    assert injected == {"k1"}
    assert [m.key for m in memories] == ["k1"]


def test_format_wiki_lines_limits_to_k():
    hits = [
        {"slug": "a", "title": "A", "excerpt": "抜粋 a", "score": 0.9},
        {"slug": "b", "title": "B", "excerpt": "抜粋 b", "score": 0.8},
        {"slug": "c", "title": "C", "excerpt": "抜粋 c", "score": 0.7},
    ]
    text = format_wiki_lines(hits, k=2)
    assert text.splitlines() == ["1. (0.9) A [a] 抜粋 a", "2. (0.8) B [b] 抜粋 b"]


# ---------------------------------------------------------------------------
# /api/search 側（ChatConfig のフォールバックと min_score ゲート）
# ---------------------------------------------------------------------------


def test_load_chat_config_falls_back_to_defaults(monkeypatch):
    from nous.api.http.routers.memory import search as search_mod

    monkeypatch.setattr(
        "nous.domain.config.chat_config.ChatConfigFileRepository.get",
        lambda self, persona: (_ for _ in ()).throw(OSError("corrupt")),
    )
    config = search_mod._load_chat_config(PERSONA)
    assert isinstance(config, ChatConfig)
    assert config.persona == PERSONA


@pytest.mark.asyncio
async def test_api_injection_drops_below_min_score_memories(monkeypatch):
    """/api/search の injection には min_score ゲートが効く（results[] は無フィルタ）。"""
    from nous.api.http.routers.memory import search as search_mod
    from nous.domain.persona.entities import PersonaState

    ctx = _ctx()
    state = PersonaState(persona=PERSONA)
    ctx.persona_service.get_context.return_value = Success(state)

    def _result(key: str, score: float):
        memory = SimpleNamespace(
            key=key,
            content=f"内容-{key}",
            confidence=1.0,
            created_at=datetime.now(UTC) - timedelta(hours=1),
            source_type="user_stated",
            kind="semantic",
        )
        return SimpleNamespace(memory=memory, score=score)

    rows = [_result("high", 0.9), _result("low", 0.05)]
    config = _config(memory_min_score=0.5)

    async def _no_context(*args, **kwargs):
        return ""

    monkeypatch.setattr("nous.application.chat.pipeline.context_loader._build_context_section", _no_context)
    injection = await search_mod._build_injection(ctx, PERSONA, rows, [], config)

    assert "内容-high" in injection
    assert "内容-low" not in injection
