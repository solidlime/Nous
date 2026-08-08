"""Tests for provider reasoning/thinking kwargs mapping (R3, R4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.anthropic import AnthropicProvider
from nous.infrastructure.llm.base import DoneEvent
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


class _FakeStream:
    """Stand-in for an async context manager that yields zero chunks."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class TestOpenAICompatReasoning:
    def _make_provider(self, base_url: str | None) -> OpenAICompatProvider:
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url=base_url)
        provider._client = MagicMock()
        create_mock = AsyncMock()
        create_mock.return_value = _FakeStream()
        provider._client.chat.completions.create = create_mock
        return provider

    def _capture_kwargs(self, provider: OpenAICompatProvider) -> dict:
        return provider._client.chat.completions.create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_openrouter_uses_reasoning_object(self):
        """OpenRouter base_url → reasoning: {"effort": X} 形式."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning"] == {"effort": "high"}
        assert "reasoning_effort" not in kwargs

    @pytest.mark.asyncio
    async def test_openai_uses_reasoning_effort(self):
        """OpenAI (default) base_url → reasoning_effort: X 形式."""
        provider = self._make_provider(base_url=None)
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "high"
        assert "reasoning" not in kwargs

    @pytest.mark.asyncio
    async def test_none_adds_nothing(self):
        """reasoning_effort=None → どちらのキーも入らない."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort=None):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs

    @pytest.mark.asyncio
    async def test_base_url_stored_on_instance(self):
        """__init__ が base_url を self.base_url に保存する."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url="https://openrouter.ai/api/v1")
        assert provider.base_url == "https://openrouter.ai/api/v1"


class TestAnthropicReasoning:
    def _make_provider(self) -> AnthropicProvider:
        provider = AnthropicProvider(api_key="test-key", model="claude-opus-4-5")
        provider._client = MagicMock()
        provider._client.messages.stream.return_value = _FakeStream()
        return provider

    def _capture_kwargs(self, provider: AnthropicProvider) -> dict:
        return provider._client.messages.stream.call_args.kwargs

    @pytest.mark.asyncio
    async def test_max_maps_to_thinking_budget(self):
        """reasoning_effort="max" → thinking: {"type": "enabled", "budget_tokens": 16384}."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", reasoning_effort="max"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 16384}

    @pytest.mark.asyncio
    async def test_low_maps_to_thinking_budget(self):
        """reasoning_effort="low" → budget_tokens 2048."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", reasoning_effort="low"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}

    @pytest.mark.asyncio
    async def test_none_adds_no_thinking(self):
        """reasoning_effort=None → thinking キーが入らない."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", reasoning_effort=None):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "thinking" not in kwargs

    @pytest.mark.asyncio
    async def test_unknown_effort_falls_back_to_medium_budget(self):
        """未知の effort → デフォルト 4096 (medium) にフォールバック."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", reasoning_effort="bogus"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}

    @pytest.mark.asyncio
    async def test_reasoning_enabled_streams_done_event(self):
        """reasoning 指定でも通常どおり DoneEvent が流れる."""
        provider = self._make_provider()
        events = []
        async for ev in provider.stream(messages=[], system="", reasoning_effort="high"):
            events.append(ev)
        assert isinstance(events[-1], DoneEvent)
