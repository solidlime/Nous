from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "tool"
    content: str
    timestamp: datetime | None = None
    time_label: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    content_parts: list[dict] | None = None  # rich content (text + images) for multimodal


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    defer_loading: bool = False  # True: send via search_tools, not directly to LLM


@dataclass
class TextDeltaEvent:
    type: Literal["text_delta"] = "text_delta"
    content: str = ""


@dataclass
class ThinkingDeltaEvent:
    type: Literal["thinking_delta"] = "thinking_delta"
    content: str = ""


@dataclass
class ToolCallEvent:
    type: Literal["tool_call"] = "tool_call"
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_use_id: str = ""


@dataclass
class DoneEvent:
    type: Literal["done"] = "done"
    full_content: str = ""
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T}


@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


ChatEvent = TextDeltaEvent | ThinkingDeltaEvent | ToolCallEvent | DoneEvent | ErrorEvent


class LLMProvider(ABC):
    def supports_vision(self) -> bool:
        """Whether this provider/model combination supports image inputs.

        Defaults to False for safety. Override in subclasses that support
        multimodal inputs.
        """
        return False

    @abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        system: str,
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[ChatEvent]: ...
