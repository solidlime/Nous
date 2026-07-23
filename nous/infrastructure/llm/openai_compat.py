from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .base import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    LLMMessage,
    LLMProvider,
    TextDeltaEvent,
    ToolCallEvent,
    ToolDefinition,
)
from .cache_utils import build_openai_system_messages

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible streaming provider (supports OpenAI and OpenRouter)."""

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: str | None = None) -> None:
        try:
            import httpx
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url or _OPENAI_BASE_URL,
                http_client=httpx.AsyncClient(timeout=httpx.Timeout(60.0)),
            )
        except ImportError as e:
            raise ImportError("openai package required: pip install openai") from e
        self.model = model

    def _to_api_messages(self, messages: list[LLMMessage]) -> list[dict]:
        result = []
        for msg in messages:
            content = msg.content

            if msg.role == "assistant" and msg.tool_calls:
                tool_calls_data = []
                for tc in msg.tool_calls:
                    tool_calls_data.append(
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"], ensure_ascii=False),
                            },
                        }
                    )
                result.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls_data,
                        "reasoning_content": "",
                    }
                )
            elif msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": content,
                    }
                )
            elif msg.role == "user" and msg.content_parts:
                # Use rich content parts (text + images) for multimodal
                logger.info(
                    "OpenAICompatProvider: using content_parts with %d parts for user message (types: %s)",
                    len(msg.content_parts),
                    [p.get("type", "?") for p in msg.content_parts],
                )
                result.append({"role": "user", "content": msg.content_parts})
            else:
                result.append({"role": msg.role, "content": content})
        return result

    async def stream(
        self,
        messages: list[LLMMessage],
        system: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float | None = None,
    ) -> AsyncIterator[ChatEvent]:
        openai_tools = []
        if tools:
            for t in tools:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.input_schema,
                        },
                    }
                )

        api_messages = build_openai_system_messages(system) + self._to_api_messages(messages)

        try:
            kwargs: dict = {
                "model": self.model,
                "messages": api_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if top_p is not None:
                kwargs["top_p"] = top_p
            if openai_tools:
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"

            kwargs["stream_options"] = {"include_usage": True}

            full_text = ""
            finish_reason = ""
            tool_calls_collected: list[ToolCallEvent] = []
            # Accumulate tool call chunks by index
            pending_tool_calls: dict[int, dict] = {}

            usage_info: dict | None = None
            async with await self._client.chat.completions.create(**kwargs) as stream:
                async for chunk in stream:
                    # Collect usage from streaming chunks (final chunk or usage-only chunk)
                    if chunk.usage:
                        usage_info = {
                            "prompt_tokens": chunk.usage.prompt_tokens,
                            "completion_tokens": chunk.usage.completion_tokens,
                            "total_tokens": chunk.usage.total_tokens,
                        }

                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue

                    if chunk.choices and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason

                    if delta.content:
                        full_text += delta.content
                        yield TextDeltaEvent(content=delta.content)

                    if delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {
                                    "id": tc_chunk.id or "",
                                    "name": tc_chunk.function.name if tc_chunk.function else "",
                                    "args_json": "",
                                }
                            if tc_chunk.id:
                                pending_tool_calls[idx]["id"] = tc_chunk.id
                            if tc_chunk.function:
                                if tc_chunk.function.name:
                                    pending_tool_calls[idx]["name"] = tc_chunk.function.name
                                if tc_chunk.function.arguments:
                                    pending_tool_calls[idx]["args_json"] += tc_chunk.function.arguments

            # Emit collected tool calls
            for idx in sorted(pending_tool_calls.keys()):
                tc_data = pending_tool_calls[idx]
                try:
                    input_data = json.loads(tc_data["args_json"]) if tc_data["args_json"] else {}
                except json.JSONDecodeError:
                    input_data = {}
                tc = ToolCallEvent(
                    tool_name=tc_data["name"],
                    tool_input=input_data,
                    tool_use_id=tc_data["id"],
                )
                tool_calls_collected.append(tc)
                yield tc

            yield DoneEvent(full_content=full_text, tool_calls=tool_calls_collected, finish_reason=finish_reason, usage=usage_info)

        except Exception as e:
            yield ErrorEvent(message=str(e))
