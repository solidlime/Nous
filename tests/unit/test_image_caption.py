"""Tests for ImageCaptioner — image caption for non-vision LLM providers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.tool_config import ToolConfig


class _MockProvider:
    """A mock LLMProvider that yields given events as an async generator."""

    def __init__(self, events):
        self._events = events

    async def stream(self, messages, system, **kwargs):
        for e in self._events:
            yield e

    def supports_vision(self):
        return True


class TestCaptionerInit:
    """ImageCaptioner initialization."""

    def test_captioner_init_without_provider(self):
        """ImageCaptioner can be initialized from ToolConfig only."""
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        config = ToolConfig(
            image_caption_enabled=True,
            image_caption_provider="openai_compat",
            image_caption_model="gpt-4o-mini",
            image_caption_api_key="test-key",
        )
        captioner = ImageCaptioner(config=config)
        assert captioner._config is config
        assert captioner._provider is None  # provider is lazy-created

    def test_captioner_init_with_provider(self):
        """ImageCaptioner accepts an existing LLMProvider."""
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        mock_provider = MagicMock()
        captioner = ImageCaptioner(provider=mock_provider)
        assert captioner._provider is mock_provider
        assert captioner._config is None


class TestCaptionSingle:
    """ImageCaptioner.caption() — single image."""

    @pytest.mark.asyncio
    async def test_caption_empty_image(self):
        """Empty base64 string returns empty caption."""
        from nous.infrastructure.llm.base import DoneEvent
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        provider = _MockProvider([DoneEvent(full_content="")])
        captioner = ImageCaptioner(provider=provider)
        result = await captioner.caption(base64_data="", mime_type="image/png")
        assert result == ""

    @pytest.mark.asyncio
    async def test_caption_success(self):
        """Successful caption call returns the LLM response text."""
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        provider = _MockProvider(
            [
                TextDeltaEvent(content="A photo of a cat sitting on a chair."),
                DoneEvent(full_content="A photo of a cat sitting on a chair."),
            ]
        )
        captioner = ImageCaptioner(provider=provider)
        result = await captioner.caption(
            base64_data="fakebase64data",
            mime_type="image/jpeg",
            hint="what is in this image?",
        )
        assert result == "A photo of a cat sitting on a chair."

    @pytest.mark.asyncio
    async def test_caption_failure_returns_empty(self):
        """When LLM call fails, caption() returns empty string without raising."""
        from nous.infrastructure.llm.base import ErrorEvent
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        provider = _MockProvider([ErrorEvent(message="API error")])
        captioner = ImageCaptioner(provider=provider)
        result = await captioner.caption(base64_data="fakebase64data")
        assert result == ""

    @pytest.mark.asyncio
    async def test_caption_exception_returns_empty(self):
        """When LLM call raises an exception, caption() returns empty string."""
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        class FailingProvider:
            async def stream(self, messages, system, **kwargs):
                raise RuntimeError("connection failed")

            def supports_vision(self):
                return True

        captioner = ImageCaptioner(provider=FailingProvider())
        result = await captioner.caption(base64_data="fakebase64")
        assert result == ""


class TestCaptionBatch:
    """ImageCaptioner.caption_batch() — multiple images."""

    @pytest.mark.asyncio
    async def test_caption_batch(self):
        """Batch captioning returns list of captions."""
        import asyncio

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        results_queue = asyncio.Queue()
        results_queue.put_nowait("A cat.")
        results_queue.put_nowait("A dog.")

        async def _stream(messages, system, **kwargs):
            label = await results_queue.get()
            yield TextDeltaEvent(content=label)
            yield DoneEvent(full_content=label)

        provider = MagicMock()
        provider.stream = _stream
        provider.supports_vision = MagicMock(return_value=True)

        captioner = ImageCaptioner(provider=provider)
        images = [
            {"base64_data": "img1data", "mime_type": "image/png"},
            {"base64_data": "img2data", "mime_type": "image/jpeg"},
        ]
        results = await captioner.caption_batch(images)
        assert sorted(results) == sorted(["A cat.", "A dog."])

    @pytest.mark.asyncio
    async def test_caption_batch_with_failures(self):
        """Batch captioning handles partial failures gracefully."""
        import asyncio

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        result_queue = asyncio.Queue()
        result_queue.put_nowait("cat")
        result_queue.put_nowait("FAIL")
        result_queue.put_nowait("bird")

        async def _stream(messages, system, **kwargs):
            label = await result_queue.get()
            if label == "FAIL":
                yield ErrorEvent(message="fail")
            elif label == "cat":
                yield TextDeltaEvent(content="A cat.")
                yield DoneEvent(full_content="A cat.")
            else:
                yield TextDeltaEvent(content="A bird.")
                yield DoneEvent(full_content="A bird.")

        provider = MagicMock()
        provider.stream = _stream
        provider.supports_vision = MagicMock(return_value=True)

        captioner = ImageCaptioner(provider=provider)
        images = [
            {"base64_data": "img1data", "mime_type": "image/png"},
            {"base64_data": "img2data", "mime_type": "image/jpeg"},
            {"base64_data": "img3data", "mime_type": "image/png"},
        ]
        results = await captioner.caption_batch(images)
        assert sorted(results) == sorted(["A cat.", "", "A bird."])

    @pytest.mark.asyncio
    async def test_caption_batch_empty(self):
        """Empty image list returns empty list."""
        from nous.infrastructure.llm.image_caption import ImageCaptioner

        provider = MagicMock()
        captioner = ImageCaptioner(provider=provider)
        results = await captioner.caption_batch([])
        assert results == []
