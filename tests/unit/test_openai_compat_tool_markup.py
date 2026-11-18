"""content に漏れたツール呼び出し記法を provider が復旧する経路。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.infrastructure.llm.base import TextDeltaEvent, ToolCallEvent
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider

LEAKED = (
    "<｜｜DSML｜｜ calls>\n"
    '<｜｜DSML｜｜ invoke name="bash">\n'
    '<｜｜DSML｜｜ parameter name="command" string="true">echo hi</｜｜DSML｜｜ parameter>\n'
    "</｜｜DSML｜｜ invoke>\n"
    "</｜｜DSML｜｜ calls>"
)


class _ChunkStream:
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


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None), finish_reason=None)],
        usage=None,
    )


async def _events(chunks: list) -> list:
    provider = OpenAICompatProvider(api_key="k", model="m", base_url=None)
    provider._client = MagicMock()
    provider._client.chat.completions.create = AsyncMock(return_value=_ChunkStream(chunks))
    return [ev async for ev in provider.stream(messages=[], system="")]


@pytest.mark.asyncio
async def test_leaked_markup_is_not_shown_and_becomes_tool_call():
    events = await _events([_chunk("調べるのよ。\n"), _chunk(LEAKED)])

    text = "".join(e.content for e in events if isinstance(e, TextDeltaEvent))
    assert "DSML" not in text
    assert "調べるのよ。" in text

    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(calls) == 1
    assert calls[0].tool_name == "bash"
    assert calls[0].tool_input == {"command": "echo hi"}
    assert calls[0].tool_use_id.startswith("recovered_")


@pytest.mark.asyncio
async def test_markup_split_across_chunks_is_recovered():
    # 1文字ずつ届いても本文に漏れず、呼び出しとして復旧する
    events = await _events([_chunk(ch) for ch in LEAKED])

    assert not "".join(e.content for e in events if isinstance(e, TextDeltaEvent)).count("DSML")
    assert [e.tool_name for e in events if isinstance(e, ToolCallEvent)] == ["bash"]


@pytest.mark.asyncio
async def test_unparsable_markup_is_dropped_not_shown():
    events = await _events([_chunk("<｜｜DSML｜｜ calls>\n壊れた本文\n</｜｜DSML｜｜ calls>")])

    assert "".join(e.content for e in events if isinstance(e, TextDeltaEvent)) == ""
    assert not [e for e in events if isinstance(e, ToolCallEvent)]
