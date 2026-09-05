"""L0-L3 drift chain regression (Task 3).

judge -> _with_drift -> run_memory_llm保存 -> _build_context_section「前回の反省」。
本番コード実パス。フェイクはLLM境界(get_provider)とDB境界(memory/search)のみ。
本番DB書込なし。細部の正規化仕様は test_character_drift.py に委ね、ここでは鎖の完走のみ見る。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.memory_extractor import run_memory_llm
from nous.application.chat.pipeline.context_loader import _build_context_section
from nous.application.chat.pipeline.post import _with_drift
from nous.domain.shared.result import Success
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent


def _make_config():
    config = MagicMock()
    config.provider = "test"
    config.extract_model = "m"
    config.get_effective_api_key.return_value = "key"
    config.get_effective_model.return_value = "m"
    config.get_effective_base_url.return_value = ""
    config.system_prompt = "あなたはヘルタである。"
    config.extract_max_tokens = 500
    return config


def _make_chain_ctx():
    stored: list = []
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.vector_store = None
    ctx.search_engine.search = AsyncMock(return_value=MagicMock(is_ok=False))
    empty = SimpleNamespace(
        user_info={}, emotion="", mental_state="", physical_state="",
        environment="", fatigue=None, warmth=None, arousal=None,
    )
    ctx.persona_service.get_context = MagicMock(return_value=Success(empty))
    ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.search_items = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.connection.get_memory_db.side_effect = Exception("no db in unit test")

    async def _create_memory(content, importance=0.6, tags=None, emotion="neutral", **kw):
        obj = SimpleNamespace(
            key=f"mem_{len(stored) + 1}", content=content,
            tags=list(tags or []), importance=importance, valid_until=kw.get("valid_until"),
        )
        stored.append(obj)
        mem = MagicMock()
        mem.key = obj.key
        mem.content = obj.content
        return Success(mem)

    ctx.memory_service.create_memory = AsyncMock(side_effect=_create_memory)

    def _by_tags(tags):
        if "character_drift" in tags:
            return Success([m for m in stored if "character_drift" in (m.tags or [])])
        return Success([])

    ctx.memory_service.get_by_tags = MagicMock(side_effect=_by_tags)
    return ctx


def _provider_with(text):
    provider = MagicMock()

    async def _stream(**kwargs):
        yield TextDeltaEvent(content=text)
        yield DoneEvent(full_content=text)

    provider.stream = _stream
    return provider


def _judge_json(violation="tone", detail="一人称が俺だった"):
    return json.dumps({"violation": violation, "detail": detail}, ensure_ascii=False)


def _memory_json(content, tags, importance):
    return json.dumps({
        "facts": [{"content": content, "importance": importance, "tags": tags, "emotion": "neutral"}],
        "goals": [], "promises": [], "context_update": {}, "inventory_update": {},
    }, ensure_ascii=False)


def _make_state():
    return SimpleNamespace(
        persona="herta", emotion="", emotion_intensity=0.0, mental_state="",
        physical_state="", environment="", relationship_status="",
        user_info={}, persona_info={},
    )


async def _run_chain(ctx, config, memory_text, judge_text=None):
    from nous.application.chat import character_judge as cj

    judge_text = judge_text or _judge_json()
    with (
        patch.object(cj, "get_provider", return_value=_provider_with(judge_text)),
        patch("nous.application.chat.memory_extractor.get_provider",
              return_value=_provider_with(memory_text)),
    ):
        from nous.application.chat.character_judge import judge_character

        judgment = await judge_character(config, "あなたはヘルタである。", "俺はすごいぜ")
        payload = _with_drift({"user": "u", "assistant": "俺はすごいぜ"}, judgment)
        result = await run_memory_llm(ctx, config, payload)
        section = await _build_context_section(ctx, _make_state())
    return judgment, payload, result, section


class TestDriftChain:
    @pytest.mark.asyncio
    async def test_chain_end_to_end(self):
        ctx, config = _make_chain_ctx(), _make_config()
        content = "私は一人称を誤った。次は私で通す。"
        judgment, payload, _result, section = await _run_chain(
            ctx, config, _memory_json(content, ["character_drift", "tone"], 0.85))
        assert judgment and judgment["violation"] == "tone"
        assert payload["drift"]["violation"] == "tone"
        assert "前回の反省" in section
        assert content in section

    @pytest.mark.asyncio
    async def test_chain_survives_broken_tags(self):
        ctx, config = _make_chain_ctx(), _make_config()
        content = "私は迎合しすぎた。次は突き放す。"
        _judgment, _payload, _result, section = await _run_chain(
            ctx, config, _memory_json(content, ["Character_Drift"], 0.2))
        assert "前回の反省" in section
        assert content in section
