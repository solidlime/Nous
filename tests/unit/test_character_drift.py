"""Tests for character-drift accumulation (spec: 2026-09-05-drift-memory-design)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.memory_extractor import run_memory_llm
from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT, _build_drift_section
from nous.application.chat.pipeline.post import _with_drift
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


class TestDriftSection:
    def test_none_returns_empty(self):
        assert _build_drift_section(None) == ""

    def test_violation_renders_type_and_detail(self):
        section = _build_drift_section({"violation": "tone", "detail": "一人称が俺だった"})
        assert "tone" in section
        assert "一人称が俺だった" in section

    def test_template_has_placeholder(self):
        assert "{drift_section}" in _MEMORY_LLM_PROMPT

    def test_template_has_drift_rule(self):
        assert "character_drift" in _MEMORY_LLM_PROMPT


def _make_ctx():
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.vector_store = None
    ctx.search_engine.search = AsyncMock(return_value=MagicMock(is_ok=False))
    mem = MagicMock()
    mem.key = "mem_test"
    mem.content = "dummy"
    ctx.memory_service.create_memory = AsyncMock(return_value=Success(mem))
    ctx.memory_service.get_by_tags = MagicMock(return_value=MagicMock(is_ok=False, value=[]))
    ctx.persona_service.get_context = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.search_items = MagicMock(return_value=MagicMock(is_ok=False))
    return ctx


def _make_config():
    config = MagicMock()
    config.extract_model = ""
    config.get_effective_api_key.return_value = "key"
    config.get_effective_model.return_value = "model"
    return config


class TestDriftForwarding:
    @pytest.mark.asyncio
    async def test_run_memory_llm_forwards_drift(self):
        ctx, config = _make_ctx(), _make_config()
        drift = {"violation": "tone", "detail": "一人称が俺だった"}
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value={}),
            ) as mock_process,
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a", "drift": drift})
        assert mock_process.await_args.kwargs["drift"] == drift

    @pytest.mark.asyncio
    async def test_run_memory_llm_no_drift_defaults_none(self):
        ctx, config = _make_ctx(), _make_config()
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value={}),
            ) as mock_process,
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        assert mock_process.await_args.kwargs["drift"] is None

    @pytest.mark.asyncio
    async def test_drift_fact_saved_with_valid_until(self):
        ctx, config = _make_ctx(), _make_config()
        result = {
            "facts": [
                {
                    "content": "私は一人称を間違えた。次は私で通すべきだった。",
                    "importance": 0.85,
                    "tags": ["character_drift", "tone"],
                    "emotion": "neutral",
                }
            ],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value=result),
            ),
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["character_drift", "tone"]
        assert kwargs["importance"] == 0.85
        valid_until = kwargs["valid_until"]
        delta = valid_until - get_now()
        assert timedelta(days=6) < delta <= timedelta(days=7, seconds=60)

    @pytest.mark.asyncio
    async def test_normal_fact_saved_without_valid_until(self):
        ctx, config = _make_ctx(), _make_config()
        result = {
            "facts": [{"content": "ユーザーは猫が好き", "importance": 0.7, "tags": ["preference"], "emotion": "joy"}],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value=result),
            ),
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert "valid_until" not in kwargs


class TestWithDrift:
    def test_violation_attaches_drift(self):
        payload = {"user": "u", "assistant": "a"}
        out = _with_drift(payload, {"violation": "compliance", "detail": "迎合が過ぎた"})
        assert out["drift"] == {"violation": "compliance", "detail": "迎合が過ぎた"}
        assert "drift" not in payload

    def test_none_violation_returns_same(self):
        payload = {"user": "u", "assistant": "a"}
        assert _with_drift(payload, {"violation": "none", "detail": ""}) == payload
        assert _with_drift(payload, None) == payload

    def test_missing_detail_defaults_empty(self):
        out = _with_drift({"user": "u", "assistant": "a"}, {"violation": "character"})
        assert out["drift"] == {"violation": "character", "detail": ""}
