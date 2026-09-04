"""_expand_segments: チャットセグメント展開（tree_session.py が利用）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import relative_time_str
from nous.infrastructure.llm.base import LLMMessage

if TYPE_CHECKING:
    from datetime import datetime


def _expand_segments(segments: list[dict], ts: datetime, now: datetime) -> list[LLMMessage]:
    """Expand segment sequence into proper assistant/tool LLMMessage list.

    Segments record the chronological order of text, tool_call, and tool_result
    within one assistant turn. This method decomposes them into the
    assistant(tool_calls) → tool → assistant(...) sequence expected by LLM APIs.
    """
    label = relative_time_str(ts, now)
    result: list[LLMMessage] = []
    current_text = ""
    current_tool_calls: list[dict] = []

    def _flush_assistant() -> None:
        nonlocal current_text, current_tool_calls
        if current_text or current_tool_calls:
            result.append(
                LLMMessage(
                    role="assistant",
                    content=current_text,
                    timestamp=ts,
                    time_label=label,
                    tool_calls=list(current_tool_calls) if current_tool_calls else None,
                )
            )
            current_text = ""
            current_tool_calls = []

    for seg in segments:
        seg_type = seg.get("type", "")
        if seg_type == "text":
            current_text += seg.get("content", "")
        elif seg_type == "tool_call":
            current_tool_calls.append(
                {
                    "id": seg.get("id", ""),
                    "name": seg.get("name", ""),
                    "input": seg.get("input", {}),
                }
            )
        elif seg_type == "tool_result":
            _flush_assistant()
            raw_result = seg.get("result", "")
            if isinstance(raw_result, dict):
                content = json.dumps(raw_result, ensure_ascii=False)
            elif isinstance(raw_result, str):
                content = raw_result
            else:
                content = str(raw_result)
            result.append(
                LLMMessage(
                    role="tool",
                    content=content,
                    tool_call_id=seg.get("id", ""),
                    timestamp=ts,
                    time_label=label,
                )
            )
    _flush_assistant()
    return result
