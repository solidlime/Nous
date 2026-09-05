"""Error-message sanitization for OpenAICompatProvider (HTML-body guard)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.base import ErrorEvent
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


def _make_failing_provider(exc: Exception) -> OpenAICompatProvider:
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider.model = "test-model"
    provider.base_url = "https://opencode.ai"
    provider._client = MagicMock()
    provider._client.chat.completions.create = AsyncMock(side_effect=exc)
    return provider


async def _collect_error(provider: OpenAICompatProvider) -> ErrorEvent:
    events = []
    async for ev in provider.stream(messages=[], system=""):
        events.append(ev)
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    return errors[0]


@pytest.mark.asyncio
async def test_html_error_body_is_sanitized():
    raw = "Error code: 404 - <!DOCTYPE html><html><body>" + "x" * 5000 + "</body></html>"
    err = await _collect_error(_make_failing_provider(Exception(raw)))
    assert "<html" not in err.message.lower()
    assert "<!doctype" not in err.message.lower()
    assert "404" in err.message
    assert "Base URL" in err.message
    assert len(err.message) <= 300


@pytest.mark.asyncio
async def test_long_plain_error_is_truncated():
    err = await _collect_error(_make_failing_provider(Exception("y" * 1000)))
    assert len(err.message) <= 310


@pytest.mark.asyncio
async def test_short_plain_error_passthrough():
    err = await _collect_error(_make_failing_provider(Exception("boom")))
    assert err.message == "boom"
