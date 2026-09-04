"""Tests for LLM provider vision support detection."""

from __future__ import annotations

from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


class TestOpenAIVision:
    def test_gpt4o_supports_vision(self):
        """OpenAICompatProvider: gpt-4o supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o")
        assert provider.supports_vision() is True

    def test_gpt4_turbo_supports_vision(self):
        """OpenAICompatProvider: gpt-4-turbo supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4-turbo")
        assert provider.supports_vision() is True

    def test_gpt4_vision_supports_vision(self):
        """OpenAICompatProvider: gpt-4-vision-preview supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4-vision-preview")
        assert provider.supports_vision() is True

    def test_o1_supports_vision(self):
        """OpenAICompatProvider: o1 supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="o1")
        assert provider.supports_vision() is True

    def test_o3_supports_vision(self):
        """OpenAICompatProvider: o3 supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="o3-mini")
        assert provider.supports_vision() is True

    def test_o4_mini_supports_vision(self):
        """OpenAICompatProvider: o4-mini supports vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="o4-mini")
        assert provider.supports_vision() is True

    def test_gpt35_no_vision(self):
        """OpenAICompatProvider: gpt-3.5 does not support vision."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-3.5-turbo")
        assert provider.supports_vision() is False

    def test_openrouter_vision_model(self):
        """OpenAICompatProvider: OpenRouter model with 'vision' in name."""
        provider = OpenAICompatProvider(
            api_key="test-key",
            model="anthropic/claude-3-vision",
            base_url="https://openrouter.ai/api/v1",
        )
        assert provider.supports_vision() is True

    def test_openrouter_non_vision(self):
        """OpenAICompatProvider: OpenRouter model without vision in name defaults to True."""
        provider = OpenAICompatProvider(
            api_key="test-key",
            model="anthropic/claude-3-opus",
            base_url="https://openrouter.ai/api/v1",
        )
        assert provider.supports_vision() is True

    def test_unknown_model_defaults_true(self):
        """OpenAICompatProvider: unknown model names default to True (safe side)."""
        provider = OpenAICompatProvider(api_key="test-key", model="custom-model-v42")
        assert provider.supports_vision() is True
