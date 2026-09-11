"""Spec F (2026-09-12): MemoryLLM context/item extractor split."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from nous.application.chat.memory_extractor import MemoryLLM


def test_item_mode_uses_item_llm_dedicated(monkeypatch):
    cfg = MagicMock()
    cfg.extract_model = ""
    cfg.get_effective_model = lambda: "chat-model"
    cfg.get_effective_api_key = lambda: "sk"
    cfg.get_effective_base_url = lambda: "http://b"
    cfg.provider = "openai_compat"
    cfg.item_llm_dedicated = True
    cfg.item_llm_model = "item-model"
    cfg.item_llm_api_key = ""
    cfg.item_llm_base_url = ""
    cfg.item_llm_provider = ""

    got: dict = {}

    def fake_get_provider(provider, api_key, model, base_url):
        got.update(provider=provider, api_key=api_key, model=model, base_url=base_url)
        raise RuntimeError("stop")

    monkeypatch.setattr("nous.application.chat.memory_extractor.get_provider", fake_get_provider)
    asyncio.run(MemoryLLM().process(cfg, "u", "a", inventory="i", mode="item"))
    assert got["model"] == "item-model" and got["provider"] == "openai_compat"


def test_context_mode_uses_extract_model_not_item(monkeypatch):
    """context 側は item 専用設定の影響を受けず extract_model を使う。"""
    cfg = MagicMock()
    cfg.extract_model = "ctx-model"
    cfg.get_effective_model = lambda: "chat-model"
    cfg.get_effective_api_key = lambda: "sk"
    cfg.get_effective_base_url = lambda: "http://b"
    cfg.provider = "openai_compat"
    cfg.item_llm_dedicated = True
    cfg.item_llm_model = "item-model"
    cfg.item_llm_api_key = "item-sk"
    cfg.item_llm_base_url = "http://item"
    cfg.item_llm_provider = "other"

    got: dict = {}

    def fake_get_provider(provider, api_key, model, base_url):
        got.update(provider=provider, api_key=api_key, model=model, base_url=base_url)
        raise RuntimeError("stop")

    monkeypatch.setattr("nous.application.chat.memory_extractor.get_provider", fake_get_provider)
    asyncio.run(MemoryLLM().process(cfg, "u", "a", mode="context"))
    assert got["model"] == "ctx-model" and got["provider"] == "openai_compat"


def test_prompts_are_split():
    from nous.application.chat.memory_prompts import _CONTEXT_LLM_PROMPT, _ITEM_LLM_PROMPT

    assert "inventory_update" not in _CONTEXT_LLM_PROMPT
    assert "facts" not in _ITEM_LLM_PROMPT
    assert '"inventory_update"' in _ITEM_LLM_PROMPT
