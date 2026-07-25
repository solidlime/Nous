"""SessionWindow: チャット会話ウィンドウ管理の基底クラス。"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    import asyncio
    import sqlite3
    from collections.abc import Callable

logger = get_logger(__name__)


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


class SessionWindow:
    def __init__(self, max_messages: int = 200, batch_size: int = 10) -> None:
        self._max_messages: int = max_messages
        self._messages: list[dict] = []
        self._timestamps: list[datetime] = []
        self._db: sqlite3.Connection | None = None
        self._persona: str = ""
        self._session_id: str = ""
        self._persisted_count: int = 0
        self._batch_size: int = batch_size
        self.pending_memory_task: asyncio.Task | None = None
        self.evict_callback: Callable[[list[dict]], None] | None = None

    def attach_db(self, db: sqlite3.Connection, persona: str, session_id: str) -> None:
        """SQLite接続とセッション識別子を紐付ける。"""
        self._db = db
        self._persona = persona
        self._session_id = session_id

    def add(
        self,
        role: str,
        content: str,
        ts: datetime | None = None,
        tool_calls: list[dict] | None = None,
        segments: list[dict] | None = None,
    ) -> None:
        if len(self._messages) >= self._max_messages:
            overflow = len(self._messages) - self._max_messages + 1
            evicted = self._messages[:overflow]
            if self.evict_callback is not None and evicted:
                with contextlib.suppress(Exception):
                    self.evict_callback(evicted)
            self._messages = self._messages[overflow:]
            self._timestamps = self._timestamps[overflow:]
            self._persisted_count = max(0, self._persisted_count - overflow)
        msg: dict[str, object] = {"role": role, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if segments:
            msg["segments"] = segments
        self._messages.append(msg)
        self._timestamps.append(ts or get_now())
        if len(self._messages) - self._persisted_count >= self._batch_size:
            self._persist()

    def update_message(self, message_index: int, new_content: str) -> dict | None:
        if message_index < 0 or message_index >= len(self._messages):
            return None
        self._messages[message_index]["content"] = new_content
        self._persist()
        return dict(self._messages[message_index])

    def truncate_to(self, message_index: int) -> list[dict]:
        if message_index < 0:
            message_index = 0
        if message_index > len(self._messages):
            message_index = len(self._messages)
        removed = list(self._messages[message_index:])
        self._messages = self._messages[:message_index]
        self._timestamps = self._timestamps[:message_index]
        if message_index < self._persisted_count:
            self._persisted_count = message_index
        self._persist()
        return removed

    def flush(self) -> None:
        self._persist()

    def _persist(self) -> None:
        if self._db is None or not self._persona or not self._session_id:
            return
        try:
            messages_json = json.dumps(list(self._messages), ensure_ascii=False)
            timestamps_json = json.dumps([t.isoformat() for t in self._timestamps], ensure_ascii=False)
            now_str = get_now().isoformat()
            self._db.execute(
                "INSERT OR REPLACE INTO chat_sessions"
                " (persona, session_id, messages, timestamps, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (self._persona, self._session_id, messages_json, timestamps_json, now_str),
            )
            self._persisted_count = len(self._messages)
        except Exception as e:
            logger.warning("SessionWindow._persist failed: %s", e)

    @classmethod
    def from_db(
        cls,
        db: sqlite3.Connection,
        persona: str,
        session_id: str,
        max_messages: int = 200,
    ) -> SessionWindow | None:
        try:
            row = db.execute(
                "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            ).fetchone()
            if row is None:
                return None
            window = cls(max_messages=max_messages)
            window.attach_db(db, persona, session_id)
            messages: list[dict] = json.loads(row["messages"] if hasattr(row, "keys") else row[0])
            timestamps_raw: list[str] = json.loads(row["timestamps"] if hasattr(row, "keys") else row[1])
            for msg, ts_str in zip(messages, timestamps_raw, strict=False):
                window._messages.append(msg)
                window._timestamps.append(datetime.fromisoformat(ts_str))
            window._persisted_count = len(window._messages)
            logger.debug("SessionWindow: loaded %d messages from SQLite (persona=%s)", len(messages), persona)
            return window
        except Exception as e:
            logger.warning("SessionWindow.from_db failed: %s", e)
            return None

    @staticmethod
    def _expand_segments(segments: list[dict], ts: datetime, now: datetime) -> list[LLMMessage]:
        return _expand_segments(segments, ts, now)

    def get_labeled_messages(self, now: datetime | None = None) -> list[LLMMessage]:
        if now is None:
            now = get_now()
        result = []
        for msg, ts in zip(self._messages, self._timestamps, strict=False):
            segments = msg.get("segments")
            if segments:
                result.extend(self._expand_segments(segments, ts, now))
            else:
                label = relative_time_str(ts, now)
                result.append(
                    LLMMessage(
                        role=msg["role"],
                        content=msg["content"],
                        timestamp=ts,
                        time_label=label,
                        tool_calls=msg.get("tool_calls"),
                    )
                )
        return result

    def get_last_assistant_content(self) -> str | None:
        for msg in reversed(self._messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    def get_message_count(self) -> int:
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
