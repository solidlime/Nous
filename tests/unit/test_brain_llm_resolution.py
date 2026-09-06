"""Tests for brain_llm_* resolution chain in AppContext._init_enricher (Task B1).

Covers: ON/OFF × cfg None/present × provider match/mismatch × empty-field
fallback × reload_enricher swap.
"""

from __future__ import annotations

import logging

from nous.application.use_cases import AppContext
from nous.domain.chat_config import ChatConfig
from nous.domain.provider_config import ProviderConfig


class _MemoryEnrichmentCfg:
    """Standalone settings.memory_enrichment stand-in (cfg None path)."""

    enabled = True
    provider = "openrouter"
    api_key = None
    model = "openai/gpt-4o-mini"
    base_url = "https://openrouter.ai/api/v1"
    min_chars = 10

    def get_effective_api_key(self, settings) -> str:  # noqa: ANN001
        return "legacy-key"


class _Settings:
    openrouter_api_key = ""
    anthropic_api_key = ""
    openai_api_key = ""
    google_api_key = ""
    opencode_go_api_key = ""
    memory_enrichment = _MemoryEnrichmentCfg()


def _ctx(cfg: ChatConfig | None) -> AppContext:
    """Bare AppContext with only what _init_enricher touches."""
    ctx = object.__new__(AppContext)
    ctx._config = cfg  # noqa: SLF001
    ctx.settings = _Settings()  # noqa: SLF001
    return ctx


def _cfg(**session_overrides) -> ChatConfig:
    """ChatConfig with provider_config + session overrides via flat keys."""
    data = {
        "memory_enrichment_enabled": True,
        "provider_config": ProviderConfig(
            provider="anthropic", model="chat-model", api_key="chat-key", base_url="https://chat.url/v1"
        ),
    }
    data.update(session_overrides)
    return ChatConfig(**data)


class TestCfgNone:
    def test_uses_legacy_settings_chain(self):
        """cfg None → settings.memory_enrichment chain unchanged."""
        ctx = _ctx(None)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._provider_name == "openrouter"
        assert ctx._enricher._model == "openai/gpt-4o-mini"
        assert ctx._enricher._api_key == "legacy-key"
        assert ctx._enricher._base_url == "https://openrouter.ai/api/v1"


class TestToggleOff:
    def test_uses_chat_four_piece_set(self):
        """OFF → chat provider/model/base_url/api_key, no mixed provider."""
        ctx = _ctx(_cfg())
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "anthropic"
        assert e._model == "chat-model"
        assert e._base_url == "https://chat.url/v1"
        assert e._api_key == "chat-key"


class TestToggleOn:
    def test_dedicated_values_win(self):
        """ON with all brain_llm_* set → dedicated 4-piece."""
        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="openai",
            brain_llm_model="brain-model",
            brain_llm_base_url="https://brain.url/v1",
            brain_llm_api_key="brain-key",
        )
        ctx = _ctx(cfg)
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "openai"
        assert e._model == "brain-model"
        assert e._base_url == "https://brain.url/v1"
        assert e._api_key == "brain-key"

    def test_empty_fields_fall_back_to_settings_chain(self, monkeypatch):
        """ON with empty fields → settings.memory_enrichment fallback chain."""
        monkeypatch.setattr(_Settings, "openrouter_api_key", "settings-key", raising=False)
        cfg = _cfg(brain_llm_dedicated=True)  # brain_llm_* all empty
        ctx = _ctx(cfg)
        ctx._init_enricher()
        e = ctx._enricher
        assert e is not None
        assert e._provider_name == "openrouter"  # settings fallback
        assert e._model == "openai/gpt-4o-mini"
        assert e._base_url == "https://openrouter.ai/api/v1"
        assert e._api_key == "settings-key"

    def test_chat_key_fallback_when_provider_matches(self):
        """ON: chat api_key is the final fallback ONLY when providers match."""
        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="anthropic",  # == chat provider
        )
        ctx = _ctx(cfg)
        ctx._init_enricher()
        assert ctx._enricher is not None
        assert ctx._enricher._api_key == "chat-key"

    def test_no_chat_key_fallback_when_provider_mismatches(self, caplog, monkeypatch):
        """ON: provider mismatch + no key → enricher=None + debug log."""
        from unittest.mock import patch

        cfg = _cfg(
            brain_llm_dedicated=True,
            brain_llm_provider="google",  # != chat provider (anthropic)
        )
        ctx = _ctx(cfg)
        with (
            caplog.at_level(logging.DEBUG),
            patch("nous.config.runtime_config.RuntimeConfigManager") as rcm,
        ):
            rcm.return_value.get_effective_value.return_value = ("", None)
            ctx._init_enricher()
        assert ctx._enricher is None
        assert any("no api_key" in r.message for r in caplog.records)


class TestReloadEnricher:
    def test_reload_enricher_swaps_enricher(self):
        """reload_enricher() re-runs the resolution chain with current config."""
        ctx = _ctx(_cfg())  # OFF → chat 4-piece
        ctx._enricher = None
        ctx.reload_enricher()
        first = ctx._enricher
        assert first is not None
        assert first._provider_name == "anthropic"

        # flip to dedicated
        ctx._config.session_config.brain_llm_dedicated = True
        ctx._config.session_config.brain_llm_api_key = "brain-key"
        ctx._config.session_config.brain_llm_provider = "openai"
        ctx.reload_enricher()
        second = ctx._enricher
        assert second is not None
        assert second is not first
        assert second._provider_name == "openai"
        assert second._api_key == "brain-key"
