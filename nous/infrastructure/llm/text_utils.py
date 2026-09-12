"""provider.stream の消費を共通化するヘルパー。

各呼び出し元の temperature/max_tokens/messages/system/reasoning_effort/tools は
そのまま渡す（挙動不変）。tools=None のときは元コード同様 tools を渡さない。
on ErrorEvent は None を返し、例外は呼び出し側へ伝播する。
"""

from __future__ import annotations

from typing import NamedTuple

from nous.infrastructure.llm.base import (
    DoneEvent,
    ErrorEvent,
    LLMMessage,
    LLMProvider,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolDefinition,
)
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)


class CollectedText(NamedTuple):
    text: str | None
    usage: dict | None
    thinking_chars: int


async def collect_text(
    provider: LLMProvider,
    *,
    messages: list[LLMMessage],
    system: str = "",
    tools: list[ToolDefinition] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    reasoning_effort: str | None = None,
) -> str | None:
    """stream を消費して TextDelta を連結した文字列を返す。

    ErrorEvent で None、それ以外は蓄積文字列（空可）。例外は呼び出し側へ伝播。
    """
    parts: list[str] = []
    if tools is None:
        stream = provider.stream(
            messages=messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
    else:
        stream = provider.stream(
            messages=messages,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
    async for event in stream:
        if isinstance(event, TextDeltaEvent):
            parts.append(event.content)
        elif isinstance(event, ErrorEvent):
            logger.warning("LLM stream error: %s", event.message)
            return None
        elif isinstance(event, DoneEvent):
            break
    return "".join(parts)


async def collect_text_with_usage(
    provider: LLMProvider,
    *,
    messages: list[LLMMessage],
    system: str = "",
    tools: list[ToolDefinition] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    reasoning_effort: str | None = None,
) -> CollectedText:
    """usage と thinking 文字数付きで stream を消費する。

    text は parts が空なら None（既存 _call_llm と同じ）。ErrorEvent で (None, None, 0)。
    thinking の budget 検知ログは各呼び出し元（application 層）で行う。
    """
    parts: list[str] = []
    usage: dict | None = None
    thinking_chars = 0
    if tools is None:
        stream = provider.stream(
            messages=messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
    else:
        stream = provider.stream(
            messages=messages,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
    async for event in stream:
        if isinstance(event, TextDeltaEvent):
            parts.append(event.content)
        elif isinstance(event, ThinkingDeltaEvent):
            thinking_chars += len(event.content)
        elif isinstance(event, ErrorEvent):
            logger.warning("LLM stream error: %s", event.message)
            return CollectedText(None, None, 0)
        elif isinstance(event, DoneEvent):
            usage = event.usage
    return CollectedText("".join(parts) if parts else None, usage, thinking_chars)
