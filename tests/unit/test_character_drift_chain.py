"""L0-L3 drift chain regression (Task 3).

judge_character → payload["drift"] → run_memory_llm 保存 → _build_context_section の
「前回の反省」。本番コード実パスを通し、フェイクは LLM 境界 (get_provider) と
DB 境界 (memory_service / search_engine) のみ。細部の正規化仕様は
test_character_drift.py に委ね、ここでは鎖の完走だけを見る。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.memory_extractor import run_memory_llm
from nous.application.chat.pipeline.context_loader import _build_context_section
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
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
    """DB 境界のフェイク。create_memory を記録し、get_by_tags で返す。"""
    stored: list = []
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.vector_store = None
    ctx.search_engine.search = AsyncMock(return_value=MagicMock(is_ok=False))
    empty = SimpleNamespace(
        user_info={},
        emotion="",
        mental_state="",
        physical_state="",
        environment="",
        fatigue=None,
        warmth=None,
        arousal=None,
    )
    ctx.persona_service.get_context = MagicMock(return_value=Success(empty))
    ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.search_items = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.connection.get_memory_db.side_effect = Exception("no db in unit test")

    async def _create_memory(content, importance=0.6, tags=None, emotion="neutral", **kw):
        obj = SimpleNamespace(
            key=f"mem_{len(stored) + 1}",
            content=content,
            tags=list(tags or []),
            importance=importance,
            valid_until=kw.get("valid_until"),
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
    return ctx, stored


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
    return json.dumps(
        {
            "facts": [{"content": content, "importance": importance, "tags": tags, "emotion": "neutral"}],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        },
        ensure_ascii=False,
    )


def _make_state():
    return SimpleNamespace(
        persona="herta",
        emotion="",
        emotion_intensity=0.0,
        mental_state="",
        physical_state="",
        environment="",
        relationship_status="",
        user_info={},
        persona_info={},
    )


async def _run_chain(ctx, config, memory_text, response="俺はすごいぜ"):
    """L0 judge → L1 payload へ drift を載せる → L2 保存 → L3 注入。

    L1 の ``_with_drift`` は 9d9e7305 で本番コードから削除済みのため、
    同じ shape（violation/detail）をここで組み立てる。judge 以降は本番実パス。
    """
    from nous.application.chat.character_judge import judge_character

    with (
        patch("nous.application.chat.character_judge.get_provider", return_value=_provider_with(_judge_json())),
        patch("nous.application.chat.memory_extractor.get_provider", return_value=_provider_with(memory_text)),
    ):
        judgment = await judge_character(config, config.system_prompt, response)
        payload = {"user": "u", "assistant": response}
        if judgment and judgment.get("violation") not in (None, "none"):
            payload["drift"] = {"violation": str(judgment["violation"]), "detail": str(judgment.get("detail", ""))}
        result = await run_memory_llm(ctx, config, payload)
        section = await _build_context_section(ctx, _make_state())
    return judgment, payload, result, section


class TestDriftChain:
    @pytest.mark.asyncio
    async def test_judge_to_memory_to_context(self):
        """L0-L3: judge の違反が drift fact として保存され、次ターンの文脈に載る。"""
        ctx, stored = _make_chain_ctx()
        config = _make_config()
        content = "私は一人称を誤った。次は私で通す。"
        judgment, payload, result, section = await _run_chain(
            ctx, config, _memory_json(content, ["character_drift", "tone"], 0.85)
        )

        # L0: judge が違反を返す
        assert judgment == {"violation": "tone", "detail": "一人称が俺だった"}
        assert payload["drift"]["violation"] == "tone"

        # L2: DB 境界へ保存され、期限付き drift fact になっている
        assert result["facts"][0]["_saved"] is True
        assert len(stored) == 1
        assert stored[0].tags == ["character_drift", "tone"]
        assert stored[0].valid_until is not None
        assert stored[0].valid_until > get_now()

        # L3: 次ターンの context section に「前回の反省」として出る
        assert "前回の反省" in section
        assert content in section

    @pytest.mark.asyncio
    async def test_chain_survives_broken_tags(self):
        """タグ崩れ + 範囲外 importance でも鎖が例外なく完走し、正規化されて注入される。"""
        ctx, stored = _make_chain_ctx()
        config = _make_config()
        content = "私は迎合しすぎた。次は突き放す。"
        judgment, _payload, _result, section = await _run_chain(
            ctx, config, _memory_json(content, ["Character_Drift"], 0.2)
        )

        assert judgment is not None and judgment["violation"] == "tone"
        assert len(stored) == 1
        assert stored[0].tags == ["character_drift", "tone"]
        assert stored[0].importance == 0.85
        assert stored[0].valid_until is not None
        assert "前回の反省" in section
        assert content in section
