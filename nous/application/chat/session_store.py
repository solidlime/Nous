"""SessionWindow + SessionManager: チャット会話ウィンドウ管理 + SQLite永続化。"""

from __future__ import annotations

import contextlib
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    import asyncio
    import sqlite3
    from collections.abc import Callable

logger = get_logger(__name__)

_CHAT_SESSIONS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS chat_sessions ("
    "persona TEXT NOT NULL, session_id TEXT NOT NULL, "
    "messages TEXT NOT NULL DEFAULT '[]', timestamps TEXT NOT NULL DEFAULT '[]', "
    "updated_at TEXT NOT NULL, PRIMARY KEY (persona, session_id))"
)


def _cleanup_expired_sessions(db: sqlite3.Connection, persona: str, ttl_days: int = 7) -> None:
    """TTLを超えた古いチャットセッションをSQLiteから削除する。"""
    try:
        cutoff = (datetime.now().astimezone() - timedelta(days=ttl_days)).isoformat()
        db.execute("DELETE FROM chat_sessions WHERE persona=? AND updated_at < ?", (persona, cutoff))
        db.commit()
    except Exception as e:
        logger.warning("_cleanup_expired_sessions failed: %s", e)


class SessionWindow:
    def __init__(self, max_turns: int = 100, max_messages: int | None = None, batch_size: int = 10) -> None:
        if max_messages is not None:
            self._max_messages: int = max_messages
        else:
            self._max_messages: int = max_turns * 2
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

    def add(self, role: str, content: str, ts: datetime | None = None, tool_calls: list[dict] | None = None) -> None:
        if len(self._messages) >= self._max_messages:
            # 溢れるメッセージを evict_callback に通知してから削除
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
        self._messages.append(msg)
        self._timestamps.append(ts or get_now())
        if len(self._messages) - self._persisted_count >= self._batch_size:
            self._persist()

    def update_message(self, message_index: int, new_content: str) -> dict | None:
        """Update the content of a single message at the given index.

        Returns the updated message dict, or None if index is out of range.
        """
        if message_index < 0 or message_index >= len(self._messages):
            return None
        self._messages[message_index]["content"] = new_content
        self._persist()
        return dict(self._messages[message_index])

    def truncate_to(self, message_index: int) -> list[dict]:
        """Keep only messages up to (not including) message_index. Returns removed messages.

        Example: truncate_to(2) on [m0, m1, m2, m3] → keeps [m0, m1], returns [m2, m3]
        """
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
        """Force-persist current window state to SQLite immediately (bypass batch_size)."""
        self._persist()

    def _persist(self) -> None:
        """現在のウィンドウ状態をSQLiteにupsertする。"""
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
            self._db.commit()
            self._persisted_count = len(self._messages)
        except Exception as e:
            logger.warning("SessionWindow._persist failed: %s", e)

    @classmethod
    def from_db(
        cls,
        db: sqlite3.Connection,
        persona: str,
        session_id: str,
        max_turns: int = 100,
        max_messages: int | None = None,
    ) -> SessionWindow | None:
        """SQLiteから既存セッションをロードする。存在しなければNoneを返す。"""
        try:
            row = db.execute(
                "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            ).fetchone()
            if row is None:
                return None
            window = cls(max_turns=max_turns, max_messages=max_messages)
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

    def get_labeled_messages(self, now: datetime | None = None) -> list[LLMMessage]:
        if now is None:
            now = get_now()
        result = []
        for msg, ts in zip(self._messages, self._timestamps, strict=False):
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
        """ウィンドウ内の直近アシスタント発言を返す（なければNone）。"""
        for msg in reversed(self._messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    def get_message_count(self) -> int:
        """Return number of messages currently in the window."""
        return len(self._messages)

    def __len__(self) -> int:
        return len(self._messages)


class SessionManager:
    def __init__(self, max_sessions: int = 100) -> None:
        self._max = max_sessions
        self._sessions: OrderedDict[tuple[str, str], SessionWindow] = OrderedDict()

    def get_or_create(
        self,
        persona: str,
        session_id: str,
        max_turns: int = 100,
        max_messages: int | None = None,
        db: sqlite3.Connection | None = None,
    ) -> SessionWindow:
        key = (persona, session_id)
        if key in self._sessions:
            self._sessions.move_to_end(key)
            return self._sessions[key]
        if len(self._sessions) >= self._max:
            self._sessions.popitem(last=False)

        window: SessionWindow | None = None
        if db is not None:
            try:
                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
            except Exception as _e:
                logger.warning("SessionStore: failed to init DB schema: %s", _e)
            window = SessionWindow.from_db(db, persona, session_id, max_turns, max_messages)
            if window is None:
                window = SessionWindow(max_turns=max_turns, max_messages=max_messages)
                window.attach_db(db, persona, session_id)
                _cleanup_expired_sessions(db, persona)
        else:
            window = SessionWindow(max_turns=max_turns, max_messages=max_messages)

        self._sessions[key] = window
        return window

    def clear(self, persona: str, session_id: str) -> None:
        self._sessions.pop((persona, session_id), None)

    @staticmethod
    def get_messages(db: sqlite3.Connection, persona: str, session_id: str) -> list[dict]:
        """SQLite からセッションメッセージを返す（F2: 会話履歴復元用）。"""
        try:
            db.execute(_CHAT_SESSIONS_SCHEMA)
            row = db.execute(
                "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            ).fetchone()
            if row is None:
                return []
            messages: list[dict] = json.loads(row[0] if not hasattr(row, "keys") else row["messages"])
            timestamps_raw: list[str] = json.loads(row[1] if not hasattr(row, "keys") else row["timestamps"])
            result = []
            for msg, ts_str in zip(messages, timestamps_raw, strict=False):
                try:
                    dt = datetime.fromisoformat(ts_str)
                    time_label = dt.strftime("%H:%M")
                except ValueError:
                    time_label = ""
                entry: dict[str, object] = {"role": msg["role"], "content": msg["content"], "time": time_label}
                if msg.get("tool_calls"):
                    # Ensure all tool_calls have "id" field for backward compat
                    fixed_tc = []
                    for tc in msg["tool_calls"]:
                        if "id" not in tc:
                            tc = dict(tc, id="")
                        fixed_tc.append(tc)
                    entry["tool_calls"] = fixed_tc
                result.append(entry)
            return result
        except Exception as e:
            logger.warning("SessionManager.get_messages failed: %s", e)
            return []

    @staticmethod
    def delete_session(db: sqlite3.Connection, persona: str, session_id: str) -> bool:
        """SQLite からセッションを削除する（F3: 会話削除）。"""
        try:
            db.execute(
                "DELETE FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            )
            db.commit()
            return True
        except Exception as e:
            logger.warning("SessionManager.delete_session failed: %s", e)
            return False
