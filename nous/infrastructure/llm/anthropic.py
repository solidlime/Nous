from __future__ import annotations

import json
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-opus-4-5") -> None:
        try:
            import anthropic

            self._anthropic = anthropic
            self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=60.0)
        except ImportError as e:
            raise ImportError("anthropic package required: pip install anthropic") from e
        self.model = model

    def _to_api_messages(self, messages: list[LLMMessage]) -> list[dict]:
        result = []
        for msg in messages:
            content = msg.content

            if msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict] = []
                if content.strip():
                    content_blocks.append({"type": "text", "text": content})
                for tc in msg.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc["input"],
                        }
                    )
                result.append({"role": "assistant", "content": content_blocks})
            elif msg.role == "tool":
                result.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": content,
                            }
                        ],
                    }
                )
            elif msg.role == "user" and msg.content_parts:
                # Convert OpenAI-style content_parts to Anthropic native format
                anthropic_content: list[dict] = []
                for part in msg.content_parts:
                    if part["type"] == "text":
                        anthropic_content.append({"type": "text", "text": part["text"]})
                    elif part["type"] == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            # Format: data:image/png;base64,XXXX
                            header, _, b64_data = url.partition(",")
                            media_type = header[5:].split(";")[0]  # "image/png"
                            anthropic_content.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64_data,
                                    },
                                }
                            )
                result.append({"role": "user", "content": anthropic_content})
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
        anthropic_tools = []
        if tools:
            for t in tools:
                anthropic_tools.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                    }
                )

        api_messages = self._to_api_messages(messages)

        try:
            # 静的パートのプロンプトキャッシュ（cache_control: ephemeral）
            # <!-- __STATIC_END__ --> 境界で静的部分と動的部分を分離
            _BOUNDARY = "<!-- __STATIC_END__ -->"
            if _BOUNDARY in system:
                static_part, _, dynamic_part = system.partition(_BOUNDARY)
                system_content: list[dict] = [
                    {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
                ]
                if dynamic_part.strip():
                    system_content.append({"type": "text", "text": dynamic_part})
                system_param: str | list = system_content
            else:
                system_param = system

            kwargs: dict = {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system_param,
                "messages": api_messages,
                "temperature": temperature,
            }
            if top_p is not None:
                kwargs["top_p"] = top_p
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools

            full_text = ""
            finish_reason = ""
            usage_info: dict | None = None
            tool_calls_collected: list[ToolCallEvent] = []
            current_tool: dict | None = None

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", None)

                    if event_type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool = {"id": block.id, "name": block.name, "input_json": ""}

                    elif event_type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            full_text += delta.text
                            yield TextDeltaEvent(content=delta.text)
                        elif delta.type == "input_json_delta" and current_tool:
                            current_tool["input_json"] += delta.partial_json

                    elif event_type == "content_block_stop":
                        if current_tool:
                            try:
                                input_data = (
                                    json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                                )
                            except json.JSONDecodeError:
                                input_data = {}
                            tc = ToolCallEvent(
                                tool_name=current_tool["name"],
                                tool_input=input_data,
                                tool_use_id=current_tool["id"],
                            )
                            tool_calls_collected.append(tc)
                            yield tc
                            current_tool = None

                    elif event_type == "message_delta":
                        raw = getattr(event.delta, "stop_reason", "") or ""
                        reason_map = {
                            "end_turn": "stop",
                            "max_tokens": "length",
                            "tool_use": "tool_calls",
                            "stop_sequence": "stop",
                        }
                        finish_reason = reason_map.get(raw, raw)
                        # Collect usage from message_delta event
                        usage_attr = getattr(event, "usage", None)
                        if usage_attr:
                            usage_info = {
                                "prompt_tokens": usage_attr.input_tokens,
                                "completion_tokens": usage_attr.output_tokens,
                                "total_tokens": usage_attr.input_tokens + usage_attr.output_tokens,
                            }

            yield DoneEvent(full_content=full_text, tool_calls=tool_calls_collected, finish_reason=finish_reason, usage=usage_info)

        except Exception as e:
            yield ErrorEvent(message=str(e))
