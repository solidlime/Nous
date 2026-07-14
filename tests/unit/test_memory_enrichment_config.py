"""Tests for MemoryEnrichmentConfig.get_effective_api_key()."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nous.config.settings import MemoryEnrichmentConfig, Settings


class TestGetEffectiveApiKey:
    """4-stage fallback chain: explicit → global key → RuntimeConfig → legacy env."""

    def test_explicit_key(self):
        """Stage 1: explicit api_key is returned directly."""
        config = MemoryEnrichmentConfig(api_key="sk-explicit")
        settings = Settings()
        assert config.get_effective_api_key(settings) == "sk-explicit"

    def test_global_openrouter_key(self):
        """Stage 2: provider=openrouter → settings.openrouter_api_key."""
        config = MemoryEnrichmentConfig(api_key=None, provider="openrouter")
        settings = Settings(openrouter_api_key="sk-global")
        assert config.get_effective_api_key(settings) == "sk-global"

    def test_global_anthropic_key(self):
        """Stage 2: provider=anthropic → settings.anthropic_api_key."""
        config = MemoryEnrichmentConfig(api_key=None, provider="anthropic")
        settings = Settings(anthropic_api_key="sk-ant")
        assert config.get_effective_api_key(settings) == "sk-ant"

    def test_global_openai_key(self):
        """Stage 2: provider=openai → settings.openai_api_key."""
        config = MemoryEnrichmentConfig(api_key=None, provider="openai")
        settings = Settings(openai_api_key="sk-oai")
        assert config.get_effective_api_key(settings) == "sk-oai"

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_all_fallbacks_exhausted_returns_empty(self, mock_get_eff):
        """All stages empty → returns empty string."""
        mock_get_eff.return_value = ("", "")
        config = MemoryEnrichmentConfig(api_key=None, provider="openrouter")
        settings = Settings()
        settings.openrouter_api_key = ""
        settings.openai_api_key = ""
        settings.anthropic_api_key = ""
        assert config.get_effective_api_key(settings) == ""

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_runtime_config_override(
        self, mock_get_effective_value
    ):
        """Stage 3: RuntimeConfigManager override is used when all prior stages are empty."""
        mock_get_effective_value.return_value = ("sk-override", "override")
        config = MemoryEnrichmentConfig(api_key=None, provider="openrouter")
        settings = Settings()
        settings.openrouter_api_key = ""
        settings.openai_api_key = ""
        settings.anthropic_api_key = ""
        assert config.get_effective_api_key(settings) == "sk-override"
        mock_get_effective_value.assert_called_once_with(
            "api_keys", "openrouter_api_key"
        )

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_global_key_takes_priority_over_runtime_config(
        self, mock_get_effective_value
    ):
        """Stage 2 global key should be returned before checking RuntimeConfigManager."""
        mock_get_effective_value.return_value = ("sk-override", "override")
        config = MemoryEnrichmentConfig(api_key=None, provider="openrouter")
        settings = Settings(openrouter_api_key="sk-global")
        assert config.get_effective_api_key(settings) == "sk-global"
        # RuntimeConfigManager should NOT be called since global key matched
        mock_get_effective_value.assert_not_called()

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_legacy_env_var_fallback(self, mock_get_eff, monkeypatch):
        """Stage 4: legacy env var (OPENROUTER_API_KEY) is used when all else fails."""
        mock_get_eff.return_value = ("", "")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-legacy-env")
        config = MemoryEnrichmentConfig(api_key=None, provider="openrouter")
        settings = Settings()
        settings.openrouter_api_key = ""
        settings.openai_api_key = ""
        settings.anthropic_api_key = ""
        assert config.get_effective_api_key(settings) == "sk-legacy-env"

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_legacy_env_var_anthropic(self, mock_get_eff, monkeypatch):
        """Stage 4: ANTHROPIC_API_KEY legacy env var fallback."""
        mock_get_eff.return_value = ("", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-legacy-ant")
        config = MemoryEnrichmentConfig(api_key=None, provider="anthropic")
        settings = Settings()
        settings.openrouter_api_key = ""
        settings.openai_api_key = ""
        settings.anthropic_api_key = ""
        assert config.get_effective_api_key(settings) == "sk-legacy-ant"

    @patch("nous.config.runtime_config.RuntimeConfigManager.get_effective_value")
    def test_legacy_env_var_openai(self, mock_get_eff, monkeypatch):
        """Stage 4: OPENAI_API_KEY legacy env var fallback."""
        mock_get_eff.return_value = ("", "")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-legacy-oai")
        config = MemoryEnrichmentConfig(api_key=None, provider="openai")
        settings = Settings()
        settings.openrouter_api_key = ""
        settings.openai_api_key = ""
        settings.anthropic_api_key = ""
        assert config.get_effective_api_key(settings) == "sk-legacy-oai"
