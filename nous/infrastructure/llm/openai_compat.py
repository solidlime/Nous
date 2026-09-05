from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from .base import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    LLMMessage,
    LLMProvider,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
    ToolDefinition,
)
from .cache_utils import build_openai_system_messages

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENAI_BASE_URL = "https://api.openai.com/v1"

# 旧 AnthropicProvider (anthropic.py:24) と同じ effort→budget 変換。
# Anthropic の thinking.enabled は budget_tokens 必須 (無しで 400) のため互換分岐で使う。
_EFFORT_BUDGET_MAP = {"low": 2048, "medium": 4096, "high": 8192, "max": 16384}


_VISION_MODEL_PREFIXES = (
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision",
    "o1",
    "o3",
    "o4-mini",
)

_NON_VISION_MODEL_PREFIXES = ("gpt-3.5",)

_MAX_ERROR_MESSAGE_LEN = 300


def _sanitize_error_message(raw: str) -> str:
    lowered = raw.lower()
    if "<!doctype html" in lowered or "<html" in lowered:
        m = re.search(r"(?:status(?:_code)?|error code)[^\d]*(\d{3})", raw, re.IGNORECASE)
        code = m.group(1) if m else None
        if code is None:
            m2 = re.search(r"\b([1-5]\d\d)\b", raw)
            code = m2.group(1) if m2 else "unknown"
        return (
            f"LLM request failed with HTTP {code}: got HTML page instead of API response. "
            "Base URL may point at a website rather than an API endpoint "
            "(check trailing path, e.g. missing /zen/go/v1)."
        )
    if len(raw) > _MAX_ERROR_MESSAGE_LEN:
        return raw[:_MAX_ERROR_MESSAGE_LEN]
    return raw


def _is_vision_model(model: str) -> bool:
    """Determine if the model name indicates vision support.

    Known non-vision models (gpt-3.5) return False.
    Known vision models (gpt-4o, gpt-4-turbo, o1, etc.) return True.
    All other models default to True (safe side — API errors are visible).
    """
    if model.startswith(_NON_VISION_MODEL_PREFIXES):
        return False
    if model.startswith(_VISION_MODEL_PREFIXES):
        return True
    # Unknown model / OpenRouter: default to True (safe side)
    return True


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible streaming provider (supports OpenAI and OpenRouter)."""

    def supports_vision(self) -> bool:
        return _is_vision_model(self.model)

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
        self.base_url = base_url or _OPENAI_BASE_URL

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
        reasoning_effort: str | None = None,
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
                "max_tokens": max_tokens,
                "stream": True,
            }
            if reasoning_effort:
                # 推論モデル (o1/o3/o4-mini 等) は temperature を許可しない (400 Unsupported parameter)。
                # reasoning 指定時は sampling params (temperature/top_p) を送らない
                base = self.base_url or ""
                is_anthropic_compat = "api.anthropic.com" in base or (
                    "openrouter.ai" in base and (self.model or "").startswith("anthropic/")
                )
                if is_anthropic_compat:
                    # Anthropic Messages API 互換: reasoning_effort は無視され、thinking.enabled には
                    # budget_tokens が必須 (400)。旧 AnthropicProvider と同じ effort→budget 変換を行う
                    budget = _EFFORT_BUDGET_MAP.get(reasoning_effort, 4096)
                    kwargs["max_tokens"] = max(max_tokens, budget + 1024)
                    kwargs["extra_body"] = {"thinking": {"type": "enabled", "budget_tokens": budget}}
                else:
                    # ponytail: hybrid reasoning モデル (DeepSeek V4 等) は effort だけでは thinking が
                    # 有効化されない。OpenAI互換サーバーは未知キーを黙って無視するため、両トグルを併送
                    # (DeepSeek 公式: thinking, vLLM/Alibaba 系: enable_thinking)。
                    # Anthropic 互換 (上記分岐) は未知キーを無視しないため併送対象外。
                    kwargs["reasoning_effort"] = reasoning_effort
                    kwargs["extra_body"] = {"thinking": {"type": "enabled"}, "enable_thinking": True}
                # TODO: 推論モデルは max_tokens ではなく max_completion_tokens が必要。
                # モデル名検出が必要で侵襲が大きいため次回候補（未実施）
            else:
                kwargs["temperature"] = temperature
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

                    # CoT: reasoning_content (OpenAI o-series / OpenRouter reasoning models)、
                    # フォールバック reasoning (Baseten 系 wire: commandcode.ai 実測。2026-08-29
                    # 実機 curl で delta.reasoning + reasoning_details を確認)
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                    if reasoning:
                        yield ThinkingDeltaEvent(content=reasoning)

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
                    # 引数欠損のままツールを実行させない (誤データ生成防止)。
                    # 呼び自体を履歴に載せない → dangling tool_result も発生しない
                    logger.warning(
                        "Malformed tool arguments for '%s' (id=%s), dropping tool call",
                        tc_data["name"],
                        tc_data["id"],
                    )
                    continue
                tc = ToolCallEvent(
                    tool_name=tc_data["name"],
                    tool_input=input_data,
                    tool_use_id=tc_data["id"],
                )
                tool_calls_collected.append(tc)
                yield tc

            yield DoneEvent(
                full_content=full_text, tool_calls=tool_calls_collected, finish_reason=finish_reason, usage=usage_info
            )

        except Exception as e:
            yield ErrorEvent(message=_sanitize_error_message(str(e)))
