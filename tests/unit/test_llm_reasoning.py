"""Tests for provider reasoning/thinking kwargs mapping (R3, R4) and CoT stream pickup (R3, R4 CoT)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.anthropic import AnthropicProvider
from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent, ThinkingDeltaEvent, ToolCallEvent
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
    def _make_provider(self, base_url: str | None, model: str = "gpt-4o") -> OpenAICompatProvider:
        provider = OpenAICompatProvider(api_key="test-key", model=model, base_url=base_url)
        provider._client = MagicMock()
        create_mock = AsyncMock()
        create_mock.return_value = _FakeStream()
        provider._client.chat.completions.create = create_mock
        return provider

    def _capture_kwargs(self, provider: OpenAICompatProvider) -> dict:
        return provider._client.chat.completions.create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_reasoning_sends_effort_and_extra_body(self):
        """reasoning 指定 → reasoning_effort + extra_body トグル併送 (DeepSeek V4 / vLLM 対応)."""
        provider = self._make_provider(base_url="https://api.commandcode.ai/provider/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "enable_thinking": True}

    @pytest.mark.asyncio
    async def test_none_adds_nothing(self):
        """reasoning_effort=None → effort も extra_body も入らない."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort=None):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert "extra_body" not in kwargs

    @pytest.mark.asyncio
    async def test_reasoning_drops_sampling_params(self):
        """reasoning_effort 指定時 → temperature/top_p を送らない.

        推論モデル (o1/o3/o4-mini 等) は temperature 不許可のため.
        """
        provider = self._make_provider(base_url=None)
        async for _ in provider.stream(messages=[], system="", temperature=0.7, top_p=0.9, reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs
        assert kwargs["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_no_reasoning_keeps_temperature(self):
        """reasoning_effort なし → 従来どおり temperature を送る."""
        provider = self._make_provider(base_url=None)
        async for _ in provider.stream(messages=[], system="", temperature=0.7):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_base_url_stored_on_instance(self):
        """__init__ が base_url を self.base_url に保存する."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url="https://openrouter.ai/api/v1")
        assert provider.base_url == "https://openrouter.ai/api/v1"

    @pytest.mark.asyncio
    async def test_reasoning_effort_still_sent_for_openrouter(self):
        """OpenRouter も reasoning_effort を受理する → 専用 reasoning オブジェクト分岐は廃止."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="low"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "low"
        assert "reasoning" not in kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "enable_thinking": True}

    @pytest.mark.asyncio
    async def test_anthropic_compat_sends_budget_thinking(self):
        """Anthropic 互換エンドポイント → effort/無予算 thinking は送らず budget 付き thinking を送る."""
        provider = self._make_provider(base_url="https://api.anthropic.com/v1/")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "reasoning_effort" not in kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled", "budget_tokens": 8192}}
        assert kwargs["max_tokens"] >= 8192 + 1024

    @pytest.mark.asyncio
    async def test_anthropic_compat_effort_budget_map_low_max(self):
        """low→2048 / max→16384、未知 effort→4096 フォールバック (旧 AnthropicProvider と同マップ)."""
        for effort, budget in [("low", 2048), ("max", 16384), ("bogus", 4096)]:
            provider = self._make_provider(base_url="https://api.anthropic.com/v1/")
            async for _ in provider.stream(messages=[], system="", reasoning_effort=effort, max_tokens=100):
                pass
            kwargs = self._capture_kwargs(provider)
            assert kwargs["extra_body"] == {"thinking": {"type": "enabled", "budget_tokens": budget}}, effort
            assert kwargs["max_tokens"] >= budget + 1024, effort

    @pytest.mark.asyncio
    async def test_openrouter_anthropic_model_sends_budget_thinking(self):
        """OpenRouter + anthropic/ モデル → raw thinking は Anthropic へ透過され 400 になるため budget 付き."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1", model="anthropic/claude-sonnet-4")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="medium"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "reasoning_effort" not in kwargs
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled", "budget_tokens": 4096}}
        assert kwargs["max_tokens"] >= 4096 + 1024

    @pytest.mark.asyncio
    async def test_openrouter_non_anthropic_uses_effort_and_extra_body(self):
        """OpenRouter + 非 Anthropic モデル → effort + thinking/enable_thinking 併送を維持."""
        provider = self._make_provider(base_url="https://openrouter.ai/api/v1", model="deepseek/deepseek-v4-flash")
        async for _ in provider.stream(messages=[], system="", reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["reasoning_effort"] == "high"
        assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}, "enable_thinking": True}


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


class TestAnthropicSamplingKwargs:
    """AnthropicProvider: temperature/top_p のプロバイダ境界防御."""

    def _make_provider(self) -> AnthropicProvider:
        provider = AnthropicProvider(api_key="test-key", model="claude-opus-4-5")
        provider._client = MagicMock()
        provider._client.messages.stream.return_value = _FakeStream()
        return provider

    def _capture_kwargs(self, provider: AnthropicProvider) -> dict:
        return provider._client.messages.stream.call_args.kwargs

    @pytest.mark.asyncio
    async def test_temperature_clamped_to_api_max(self):
        """temperature > 1.0 → 1.0 にクランプ（Anthropic API 制約）."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", temperature=1.8):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["temperature"] == 1.0

    @pytest.mark.asyncio
    async def test_top_p_set_drops_temperature(self):
        """top_p 設定時 → temperature は送らず top_p のみ（同時指定禁止）."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", temperature=0.7, top_p=0.9):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "temperature" not in kwargs
        assert kwargs["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_top_p_none_sends_temperature_only(self):
        """top_p=None → 従来どおり temperature のみ."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", temperature=0.7, top_p=None):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["temperature"] == 0.7
        assert "top_p" not in kwargs

    @pytest.mark.asyncio
    async def test_reasoning_effort_drops_sampling_params(self):
        """reasoning_effort 指定時 → thinking のみで temperature/top_p は送らない.

        Anthropic API は thinking 有効時のサンプリングパラメータ変更を拒否するため.
        """
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", temperature=0.7, reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "thinking" in kwargs
        assert "temperature" not in kwargs
        assert "top_p" not in kwargs

    @pytest.mark.asyncio
    async def test_reasoning_effort_with_top_p_still_no_top_p(self):
        """reasoning_effort + top_p 同時指定でも top_p は飛ばない."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", top_p=0.9, reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "thinking" in kwargs
        assert "top_p" not in kwargs
        assert "temperature" not in kwargs

    @pytest.mark.asyncio
    async def test_reasoning_high_raises_max_tokens_above_budget(self):
        """effort="high" (budget 8192) + max_tokens=8192 → max_tokens > budget_tokens に補正.

        Anthropic API は thinking 有効時 max_tokens > budget_tokens を要求するため.
        """
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", max_tokens=8192, reasoning_effort="high"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["max_tokens"] > kwargs["thinking"]["budget_tokens"]

    @pytest.mark.asyncio
    async def test_reasoning_max_raises_max_tokens_above_budget(self):
        """effort="max" (budget 16384) + デフォルト max_tokens でも違反しない."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", reasoning_effort="max"):
            pass
        kwargs = self._capture_kwargs(provider)
        assert kwargs["max_tokens"] > kwargs["thinking"]["budget_tokens"]

    @pytest.mark.asyncio
    async def test_no_reasoning_keeps_max_tokens_untouched(self):
        """thinking 無効時 → max_tokens は元の値のまま."""
        provider = self._make_provider()
        async for _ in provider.stream(messages=[], system="", max_tokens=1234):
            pass
        kwargs = self._capture_kwargs(provider)
        assert "thinking" not in kwargs
        assert kwargs["max_tokens"] == 1234


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
        events = await self._stream_events([self._chunk(content="Hello", reasoning="Hmm")])
        assert [ev.content for ev in events if isinstance(ev, ThinkingDeltaEvent)] == ["Hmm"]
        assert [ev.content for ev in events if isinstance(ev, TextDeltaEvent)] == ["Hello"]
        thinking_idx = next(i for i, ev in enumerate(events) if isinstance(ev, ThinkingDeltaEvent))
        text_idx = next(i for i, ev in enumerate(events) if isinstance(ev, TextDeltaEvent))
        assert thinking_idx < text_idx

    @pytest.mark.asyncio
    async def test_no_reasoning_no_thinking_events(self):
        """reasoning_content が無い → ThinkingDeltaEvent は出ない."""
        events = await self._stream_events([self._chunk(content="plain", reasoning=None)])
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
                SimpleNamespace(
                    type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="Final answer")
                ),
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


class TestMalformedToolArgs:
    """不正 JSON 引数のツールコール → ツールコール自体を履歴から落として実行させない."""

    @pytest.mark.asyncio
    async def test_openai_malformed_args_dropped(self):
        """OpenAICompat: args_json が不正 JSON → ToolCallEvent を出さない (実行されない)."""
        provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url=None)
        provider._client = MagicMock()
        chunk = SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_1",
                                function=SimpleNamespace(name="memory_create", arguments='{"content": "bro'),
                            )
                        ],
                    ),
                )
            ],
        )
        provider._client.chat.completions.create = AsyncMock(return_value=_ChunkStream([chunk]))

        events = []
        async for ev in provider.stream(messages=[], system=""):
            events.append(ev)

        assert not any(isinstance(ev, ToolCallEvent) for ev in events)

    @pytest.mark.asyncio
    async def test_anthropic_malformed_args_dropped(self):
        """Anthropic: input_json_delta が不正 JSON → ToolCallEvent を出さない (実行されない)."""
        provider = AnthropicProvider(api_key="test-key", model="claude-opus-4-5")
        provider._client = MagicMock()
        sdk_events = [
            SimpleNamespace(
                type="content_block_start",
                content_block=SimpleNamespace(type="tool_use", id="toolu_1", name="memory_create"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="input_json_delta", partial_json='{"content": "bro'),
            ),
            SimpleNamespace(type="content_block_stop"),
            SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="tool_use"), usage=None),
        ]
        provider._client.messages.stream.return_value = _ChunkStream(sdk_events)

        events = []
        async for ev in provider.stream(messages=[], system=""):
            events.append(ev)

        assert not any(isinstance(ev, ToolCallEvent) for ev in events)


class TestAnthropicUsageDefense:
    """message_delta.usage の None 属性でストリームが落ちない (#10)."""

    @pytest.mark.asyncio
    async def test_usage_none_fields_do_not_crash(self):
        """input_tokens/output_tokens が None → TypeError ではなく DoneEvent (0 扱い)."""
        provider = AnthropicProvider(api_key="test-key", model="claude-opus-4-5")
        provider._client = MagicMock()
        sdk_events = [
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(input_tokens=None, output_tokens=5),
            ),
        ]
        provider._client.messages.stream.return_value = _ChunkStream(sdk_events)

        events = []
        async for ev in provider.stream(messages=[], system=""):
            events.append(ev)

        done = [ev for ev in events if isinstance(ev, DoneEvent)]
        assert len(done) == 1
        assert not any(isinstance(ev, ErrorEvent) for ev in events)
        assert done[0].usage == {"prompt_tokens": 0, "completion_tokens": 5, "total_tokens": 5}
