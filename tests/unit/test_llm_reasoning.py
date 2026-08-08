"""Tests for provider reasoning/thinking kwargs mapping (R3, R4) and CoT stream pickup (R3, R4 CoT)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.anthropic import AnthropicProvider
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent, ThinkingDeltaEvent
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


class _ChunkStream:
    """Async context manager that yields the given chunks in order."""

    def __init__(self, chunks: list) -> None:
        self._chunks = list(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


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


class TestOpenAICompatCoT:
    """OpenAICompatProvider: delta.reasoning_content を ThinkingDeltaEvent として拾う (SPEC R3)."""

    @staticmethod
    def _chunk(content: str | None, reasoning: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None),
                    finish_reason=None,
                )
            ],
            usage=None,
        )

    async def _stream_events(self, chunks: list) -> list:
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url=None)
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(return_value=_ChunkStream(chunks))
        events = []
        async for ev in provider.stream(messages=[], system=""):
            events.append(ev)
        return events

    @pytest.mark.asyncio
    async def test_reasoning_content_yields_thinking_events(self):
        """reasoning_content が ThinkingDeltaEvent として text と分離して yield される."""
        events = await self._stream_events(
            [
                self._chunk(content=None, reasoning="Let me think"),
                self._chunk(content="Answer", reasoning="more"),
                self._chunk(content=None, reasoning=None),
            ]
        )
        thinking = [ev for ev in events if isinstance(ev, ThinkingDeltaEvent)]
        texts = [ev for ev in events if isinstance(ev, TextDeltaEvent)]
        assert [t.content for t in thinking] == ["Let me think", "more"]
        assert [t.content for t in texts] == ["Answer"]

    @pytest.mark.asyncio
    async def test_content_and_reasoning_in_same_chunk_yielded_in_order(self):
        """同一チャンクで content と reasoning_content の両方 → 両方 yield（reasoning が先）."""
        events = await self._stream_events(
            [self._chunk(content="Hello", reasoning="Hmm")]
        )
        assert [ev.content for ev in events if isinstance(ev, ThinkingDeltaEvent)] == ["Hmm"]
        assert [ev.content for ev in events if isinstance(ev, TextDeltaEvent)] == ["Hello"]
        thinking_idx = next(i for i, ev in enumerate(events) if isinstance(ev, ThinkingDeltaEvent))
        text_idx = next(i for i, ev in enumerate(events) if isinstance(ev, TextDeltaEvent))
        assert thinking_idx < text_idx

    @pytest.mark.asyncio
    async def test_no_reasoning_no_thinking_events(self):
        """reasoning_content が無い → ThinkingDeltaEvent は出ない."""
        events = await self._stream_events(
            [self._chunk(content="plain", reasoning=None)]
        )
        assert not any(isinstance(ev, ThinkingDeltaEvent) for ev in events)
        assert [ev.content for ev in events if isinstance(ev, TextDeltaEvent)] == ["plain"]


class TestAnthropicCoT:
    """AnthropicProvider: thinking_delta を ThinkingDeltaEvent として拾う (SPEC R4)."""

    async def _stream_events(self, sdk_events: list) -> list:
        provider = AnthropicProvider(api_key="test-key", model="claude-opus-4-5")
        provider._client = MagicMock()
        provider._client.messages.stream.return_value = _ChunkStream(sdk_events)
        events = []
        async for ev in provider.stream(messages=[], system=""):
            events.append(ev)
        return events

    @pytest.mark.asyncio
    async def test_thinking_delta_yields_thinking_events(self):
        """delta.type == "thinking_delta" → ThinkingDeltaEvent として yield され text と分離."""
        events = await self._stream_events(
            [
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="thinking_delta", thinking="Hmm, let me consider"),
                ),
                SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="Final answer")),
                SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"), usage=None),
            ]
        )
        thinking = [ev for ev in events if isinstance(ev, ThinkingDeltaEvent)]
        texts = [ev for ev in events if isinstance(ev, TextDeltaEvent)]
        assert [t.content for t in thinking] == ["Hmm, let me consider"]
        assert [t.content for t in texts] == ["Final answer"]

    @pytest.mark.asyncio
    async def test_no_thinking_delta_no_thinking_events(self):
        """thinking_delta が無い → ThinkingDeltaEvent は出ない."""
        events = await self._stream_events(
            [
                SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="plain")),
                SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"), usage=None),
            ]
        )
        assert not any(isinstance(ev, ThinkingDeltaEvent) for ev in events)
        assert [ev.content for ev in events if isinstance(ev, TextDeltaEvent)] == ["plain"]


class TestToApiMessagesNoReasoningContent:
    """F2: assistant(tool_calls) メッセージに非標準 reasoning_content を含めない。"""

    def test_assistant_tool_calls_have_no_reasoning_content(self):
        from nous.infrastructure.llm.base import LLMMessage
        from nous.infrastructure.llm.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(api_key="test-key", base_url="https://openrouter.ai/api/v1")
        msgs = [
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[{"id": "call_1", "name": "search", "input": {"q": "x"}}],
            ),
        ]
        out = provider._to_api_messages(msgs)

        assert out[0]["role"] == "assistant"
        assert "reasoning_content" not in out[0]
        assert out[0]["tool_calls"][0]["id"] == "call_1"
