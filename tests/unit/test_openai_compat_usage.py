"""OpenAICompatProvider: usage の cached_tokens 観測（prompt_tokens_details の二段 None 防御）."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.base import DoneEvent
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


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


def _usage_chunk(details: object) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=10,
            total_tokens=1010,
            prompt_tokens_details=details,
        ),
    )


async def _usage_of(chunk: SimpleNamespace) -> dict | None:
    provider = OpenAICompatProvider(api_key="test-key", model="gpt-4o", base_url=None)
    provider._client = MagicMock()
    provider._client.chat.completions.create = AsyncMock(return_value=_ChunkStream([chunk]))
    async for ev in provider.stream(messages=[], system=""):
        if isinstance(ev, DoneEvent):
            return ev.usage
    return None


@pytest.mark.asyncio
async def test_cached_tokens_is_reported() -> None:
    usage = await _usage_of(_usage_chunk(SimpleNamespace(cached_tokens=768)))
    assert usage is not None
    assert usage["cached_tokens"] == 768
    assert usage["prompt_tokens"] == 1000


@pytest.mark.asyncio
async def test_missing_prompt_tokens_details_falls_back_to_zero() -> None:
    usage = await _usage_of(_usage_chunk(None))
    assert usage is not None
    assert usage["cached_tokens"] == 0


@pytest.mark.asyncio
async def test_missing_cached_tokens_falls_back_to_zero() -> None:
    usage = await _usage_of(_usage_chunk(SimpleNamespace(cached_tokens=None)))
    assert usage is not None
    assert usage["cached_tokens"] == 0
