"""MonologueGenerator unit tests (REM drain 完了時の一人称独り言生成)."""

from __future__ import annotations

import pytest

from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent
from nous.infrastructure.llm.monologue_generator import MonologueGenerator


class FakeProvider:
    """_call_llm と同じ stream プロトコルを模倣するフェイク。"""

    def __init__(self, chunks=None, error=False):
        self._chunks = chunks if chunks is not None else ["昨日の話、", "まだ頭に残ってる。"]
        self._error = error

    async def stream(self, messages=None, system=None, temperature=None, max_tokens=None):
        self.last_kwargs = {
            "messages": messages,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._error:
            yield ErrorEvent(message="boom")
            return
        for c in self._chunks:
            yield TextDeltaEvent(content=c)
        yield DoneEvent(usage={"prompt_tokens": 100, "completion_tokens": 20})


@pytest.mark.asyncio
async def test_generate_returns_joined_text():
    gen = MonologueGenerator(FakeProvider())
    out = await gen.generate("herta", ["記憶Aの本文", "記憶Bの本文"])
    assert out == "昨日の話、まだ頭に残ってる。"


@pytest.mark.asyncio
async def test_generate_error_returns_none():
    gen = MonologueGenerator(FakeProvider(error=True))
    assert await gen.generate("herta", ["x"]) is None


@pytest.mark.asyncio
async def test_generate_empty_memories_returns_none():
    gen = MonologueGenerator(FakeProvider())
    assert await gen.generate("herta", []) is None


@pytest.mark.asyncio
async def test_generate_max_five_memories_eighty_chars():
    texts = [f"{'あ' * 100}{i}" for i in range(8)]
    fake = FakeProvider()
    gen = MonologueGenerator(fake)
    await gen.generate("herta", texts)
    messages = fake.last_kwargs["messages"]
    body = messages[0].content
    # 5 件に切り詰め・80 字切り詰め
    assert body.count("\n- ") + body.count("\n処理") == 5
    assert "あ" * 81 not in body


@pytest.mark.asyncio
async def test_generate_blank_output_returns_none():
    gen = MonologueGenerator(FakeProvider(chunks=["   "]))
    assert await gen.generate("herta", ["x"]) is None


@pytest.mark.asyncio
async def test_generate_debug_logs_usage(caplog):
    import logging

    gen = MonologueGenerator(FakeProvider())
    with caplog.at_level(logging.DEBUG, logger="nous.infrastructure.llm.monologue_generator"):
        await gen.generate("herta", ["x"])
    assert "monologue usage: {'prompt_tokens': 100, 'completion_tokens': 20}" in caplog.text
