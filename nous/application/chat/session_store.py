"""SessionWindow + SessionManager: チャット会話ウィンドウ管理 + SQLite永続化。"""

from __future__ import annotations

import contextlib
import json
import uuid as _uuid
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
        if segments:
            msg["segments"] = segments
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
        max_messages: int = 200,
    ) -> SessionWindow | None:
        """SQLiteから既存セッションをロードする。存在しなければNoneを返す。"""
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


class TreeSessionWindow:
    """ツリー構造でメッセージを管理するセッションウィンドウ。

    各メッセージはUUIDで識別され、parent_idで親子関係を持つ。
    編集はインプレース上書き、ロールバックはactive_leaf_id変更のみ（非破壊）。
    """

    def __init__(self, max_messages: int = 200, batch_size: int = 10) -> None:
        self._nodes: dict[str, dict] = {}
        self._root_id: str | None = None
        self._active_leaf_id: str | None = None
        self._db: sqlite3.Connection | None = None
        self._persona: str = ""
        self._session_id: str = ""
        self._persisted_count: int = 0
        self._batch_size: int = batch_size
        self._max_messages: int = max_messages
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
    ) -> str:
        """メッセージをツリーに追加する。戻り値は生成したmsg_id。"""
        node_id = str(_uuid.uuid4())
        now = ts or get_now()
        node: dict[str, object] = {
            "id": node_id,
            "parent_id": self._active_leaf_id,
            "role": role,
            "content": content,
            "created_at": now.isoformat(),
        }
        if tool_calls:
            node["tool_calls"] = tool_calls
        if segments:
            node["segments"] = segments

        if self._root_id is None:
            self._root_id = node_id
            node["parent_id"] = None  # rootはparentを持たない

        self._nodes[node_id] = node
        self._active_leaf_id = node_id

        # max_messages 超過チェック
        path_len = self.get_message_count()
        if path_len > self._max_messages:
            overflow = path_len - self._max_messages
            evicted = self._evict_oldest(overflow)
            if evicted and self.evict_callback is not None:
                with contextlib.suppress(Exception):
                    self.evict_callback(evicted)

        if len(self._nodes) - self._persisted_count >= self._batch_size:
            self._persist()
        return node_id

    def get_active_path(self) -> list[dict]:
        """active_leaf から root まで parent_id を辿り、逆順（時系列順）で返す。"""
        if self._active_leaf_id is None:
            return []
        path: list[dict] = []
        current_id: str | None = self._active_leaf_id
        while current_id is not None:
            node = self._nodes.get(current_id)
            if node is None:
                break
            path.append(node)
            current_id = node.get("parent_id")  # type: ignore[arg-type]
        path.reverse()
        return path

    def get_message_count(self) -> int:
        """アクティブパスのメッセージ数を返す。"""
        return len(self.get_active_path())

    def __len__(self) -> int:
        return self.get_message_count()

    def get_labeled_messages(self, now: datetime | None = None) -> list[LLMMessage]:
        """アクティブパスのメッセージからLLMMessageリストを生成する。"""
        if now is None:
            now = get_now()
        result: list[LLMMessage] = []
        for node in self.get_active_path():
            segments = node.get("segments")
            ts = datetime.fromisoformat(node["created_at"])
            if segments:
                result.extend(_SessionWindow_old._expand_segments(segments, ts, now))
            else:
                label = relative_time_str(ts, now)
                result.append(
                    LLMMessage(
                        role=node["role"],
                        content=node["content"],
                        timestamp=ts,
                        time_label=label,
                        tool_calls=node.get("tool_calls"),
                    )
                )
        return result

    def get_last_assistant_content(self) -> str | None:
        """アクティブパス内の直近アシスタント発言を返す。"""
        for node in reversed(self.get_active_path()):
            if node["role"] == "assistant":
                return node["content"]
        return None

    def flush(self) -> None:
        """即時永続化。"""
        self._persist()

    # ── SessionWindow 後方互換 ──────────────────────────────────

    @property
    def _messages(self) -> list[dict]:
        """SessionWindow互換: アクティブパスを返す。"""
        return self.get_active_path()

    @property
    def _timestamps(self) -> list[datetime]:
        """SessionWindow互換: アクティブパスの created_at をdatetimeリストで返す。"""
        return [
            datetime.fromisoformat(n["created_at"])
            for n in self.get_active_path()
        ]

    def update_message(self, message_index: int, new_content: str) -> dict | None:
        """SessionWindow互換: インデックス指定でアクティブパス内のメッセージを編集。"""
        path = self.get_active_path()
        if message_index < 0 or message_index >= len(path):
            return None
        node = path[message_index]
        node["content"] = new_content
        self._persist()
        return dict(node)

    def truncate_to(self, message_index: int) -> list[dict]:
        """SessionWindow互換: アクティブパスを指定インデックスまで切り詰める。"""
        path = self.get_active_path()
        if message_index < 0:
            message_index = 0
        if message_index > len(path):
            message_index = len(path)
        if message_index >= len(path):
            return []
        removed = path[message_index:]
        # 削除対象ノードとその子孫を全て削除
        remove_ids = {n["id"] for n in removed}
        # 子孫も走査して追加
        for nid in list(remove_ids):
            for other_id, other_node in list(self._nodes.items()):
                if self._is_descendant(other_id, nid):
                    remove_ids.add(other_id)
        for nid in remove_ids:
            self._nodes.pop(nid, None)
        # active_leaf を保持する最後のノードに
        if message_index > 0:
            self._active_leaf_id = path[message_index - 1]["id"]
        elif path:
            self._active_leaf_id = path[0]["id"]
        else:
            self._active_leaf_id = None
        if message_index < self._persisted_count:
            self._persisted_count = message_index
        self._persist()
        return removed

    # ── 内部メソッド ──────────────────────────────────────────

    def _evict_oldest(self, count: int) -> list[dict]:
        """アクティブパスのroot側から古いノードを削除する。"""
        path = self.get_active_path()
        if not path or count <= 0:
            return []
        if count >= len(path):
            count = max(1, len(path) - 1)  # 最低1件は残す
        evicted: list[dict] = []
        for node in path[:count]:
            nid = node["id"]
            if nid in self._nodes:
                evicted.append(self._nodes.pop(nid))
        if count < len(path):
            self._root_id = path[count]["id"]
        self._persisted_count = max(0, self._persisted_count - count)
        return evicted

    def _persist(self) -> None:
        """現在のツリー状態をSQLiteにupsertする。

        保存形式 (messages カラム):
        {"root_id": "...", "active_leaf_id": "...", "nodes": [...]}
        timestamps カラムは空配列（created_at に統合済み）。
        """
        if self._db is None or not self._persona or not self._session_id:
            return
        try:
            data = {
                "root_id": self._root_id,
                "active_leaf_id": self._active_leaf_id,
                "nodes": list(self._nodes.values()),
            }
            messages_json = json.dumps(data, ensure_ascii=False)
            timestamps_json = "[]"
            now_str = get_now().isoformat()
            self._db.execute(
                "INSERT OR REPLACE INTO chat_sessions"
                " (persona, session_id, messages, timestamps, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (self._persona, self._session_id, messages_json, timestamps_json, now_str),
            )
            self._db.commit()
            self._persisted_count = len(self._nodes)
        except Exception as e:
            logger.warning("TreeSessionWindow._persist failed: %s", e)

    def get_message_by_id(self, msg_id: str) -> dict | None:
        """指定されたIDのノードを返す。存在しなければNone。"""
        return self._nodes.get(msg_id)

    @classmethod
    def from_db(
        cls,
        db: sqlite3.Connection,
        persona: str,
        session_id: str,
        max_messages: int = 200,
    ) -> TreeSessionWindow | None:
        """SQLiteから既存セッションをロードする。旧形式(list)から自動マイグレーションも行う。"""
        try:
            row = db.execute(
                "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            ).fetchone()
            if row is None:
                return None

            messages_raw = row["messages"] if hasattr(row, "keys") else row[0]
            data = json.loads(messages_raw)

            window = cls(max_messages=max_messages)
            window.attach_db(db, persona, session_id)

            if isinstance(data, dict):
                # 新形式: {"root_id":..., "active_leaf_id":..., "nodes":[...]}
                window._root_id = data.get("root_id")
                window._active_leaf_id = data.get("active_leaf_id")
                for node in data.get("nodes", []):
                    window._nodes[node["id"]] = node
            elif isinstance(data, list):
                # 旧形式: list[dict] — 自動マイグレーション
                timestamps_raw: list[str] = json.loads(
                    row["timestamps"] if hasattr(row, "keys") else row[1]
                )
                prev_id: str | None = None
                for msg, ts_str in zip(data, timestamps_raw, strict=False):
                    node_id = str(_uuid.uuid4())
                    ts = datetime.fromisoformat(ts_str)
                    node: dict[str, object] = {
                        "id": node_id,
                        "parent_id": prev_id,
                        "role": msg["role"],
                        "content": msg["content"],
                        "created_at": ts.isoformat(),
                    }
                    if msg.get("tool_calls"):
                        node["tool_calls"] = msg["tool_calls"]
                    if msg.get("segments"):
                        node["segments"] = msg["segments"]
                    window._nodes[node_id] = node
                    if prev_id is None:
                        window._root_id = node_id
                    prev_id = node_id
                window._active_leaf_id = prev_id
                # マイグレーション後即座に新形式で保存
                window._persist()

            window._persisted_count = len(window._nodes)
            logger.debug("TreeSessionWindow: loaded %d nodes from SQLite (persona=%s)", len(window._nodes), persona)
            return window
        except Exception as e:
            logger.warning("TreeSessionWindow.from_db failed: %s", e)
            return None

    def edit_message(self, msg_id: str, new_content: str) -> dict | None:
        """メッセージをインプレース編集（Minimal B）。編集後永続化。"""
        node = self._nodes.get(msg_id)
        if node is None:
            return None
        node["content"] = new_content
        self._persist()
        return dict(node)

    def delete_message(self, msg_id: str) -> dict | None:
        """ノードを削除し、子ノードを削除対象のparent_idにリペアレンティングする。"""
        node = self._nodes.get(msg_id)
        if node is None:
            return None
        parent_id = node.get("parent_id")
        # リペアレンティング: 全子ノードのparent_idを削除対象のparent_idに付け替え
        for n in self._nodes.values():
            if n.get("parent_id") == msg_id:
                n["parent_id"] = parent_id
        # active_leaf_id が削除対象の子孫なら巻き戻し
        if self._is_descendant(self._active_leaf_id, msg_id):
            self._active_leaf_id = parent_id
        # root_id が削除対象なら付け替え
        if self._root_id == msg_id:
            self._root_id = parent_id
        del self._nodes[msg_id]
        self._persist()
        return node

    def rollback_to(self, msg_id: str) -> dict | None:
        """active_leaf_id を msg_id に差し替え。ノードは一切削除しない（非破壊ロールバック）。"""
        if msg_id not in self._nodes:
            return None
        old = self._active_leaf_id
        self._active_leaf_id = msg_id
        self._persist()
        return {"old_active_leaf_id": old, "new_active_leaf_id": msg_id}

    def _is_descendant(self, node_id: str | None, ancestor_id: str | None) -> bool:
        """node_id が ancestor_id の子孫かどうかを判定する。"""
        if not node_id or not ancestor_id:
            return False
        current_id: str | None = node_id
        while current_id is not None:
            if current_id == ancestor_id:
                return True
            node = self._nodes.get(current_id)
            if node is None:
                break
            current_id = node.get("parent_id")  # type: ignore[arg-type]
        return False


class SessionManager:
    def __init__(self, max_sessions: int = 100) -> None:
        self._max = max_sessions
        self._sessions: OrderedDict[tuple[str, str], TreeSessionWindow] = OrderedDict()

    def get_or_create(
        self,
        persona: str,
        session_id: str,
        max_messages: int = 200,
        db: sqlite3.Connection | None = None,
    ) -> TreeSessionWindow:
        key = (persona, session_id)
        if key in self._sessions:
            self._sessions.move_to_end(key)
            return self._sessions[key]
        if len(self._sessions) >= self._max:
            self._sessions.popitem(last=False)

        window: TreeSessionWindow | None = None
        if db is not None:
            try:
                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
            except Exception as _e:
                logger.warning("SessionStore: failed to init DB schema: %s", _e)
            window = TreeSessionWindow.from_db(db, persona, session_id, max_messages)
            if window is None:
                window = TreeSessionWindow(max_messages=max_messages)
                window.attach_db(db, persona, session_id)
                _cleanup_expired_sessions(db, persona)
        else:
            window = TreeSessionWindow(max_messages=max_messages)

        self._sessions[key] = window
        return window

    def clear(self, persona: str, session_id: str) -> None:
        self._sessions.pop((persona, session_id), None)

    @staticmethod
    def get_messages(db: sqlite3.Connection, persona: str, session_id: str) -> list[dict]:
        """SQLite からセッションメッセージを返す（F2: 会話履歴復元用）。

        新形式(dict)ではactive_pathを辿って時系列順に返す。
        旧形式(list)からも読み取り可能（idフィールドは付与されない）。
        戻り値: [{role, content, time, id?, tool_calls?, segments?}, ...]
        """
        try:
            db.execute(_CHAT_SESSIONS_SCHEMA)
            row = db.execute(
                "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
                (persona, session_id),
            ).fetchone()
            if row is None:
                return []
            messages_raw = row[0] if not hasattr(row, "keys") else row["messages"]
            data = json.loads(messages_raw)

            # 旧形式: list[dict] — 従来の処理
            if isinstance(data, list):
                timestamps_raw: list[str] = json.loads(
                    row[1] if not hasattr(row, "keys") else row["timestamps"]
                )
                result: list[dict] = []
                for msg, ts_str in zip(data, timestamps_raw, strict=False):
                    try:
                        dt = datetime.fromisoformat(ts_str)
                        time_label = dt.strftime("%H:%M")
                    except ValueError:
                        time_label = ""
                    entry: dict[str, object] = {
                        "role": msg["role"], "content": msg["content"], "time": time_label,
                    }
                    if msg.get("tool_calls"):
                        fixed_tc = []
                        for tc in msg["tool_calls"]:
                            if "id" not in tc:
                                tc = dict(tc, id="")
                            fixed_tc.append(tc)
                        entry["tool_calls"] = fixed_tc
                    if msg.get("segments"):
                        entry["segments"] = msg["segments"]
                    result.append(entry)
                return result

            # 新形式: dict — ツリーからactive_pathを再構築
            if isinstance(data, dict):
                nodes_raw: dict[str, dict] = {n["id"]: n for n in data.get("nodes", [])}
                active_leaf_id = data.get("active_leaf_id")
                # active_path を構築
                path: list[dict] = []
                current_id: str | None = active_leaf_id
                while current_id is not None:
                    node = nodes_raw.get(current_id)
                    if node is None:
                        break
                    path.append(node)
                    current_id = node.get("parent_id")
                path.reverse()

                result = []
                for node in path:
                    try:
                        dt = datetime.fromisoformat(node["created_at"])
                        time_label = dt.strftime("%H:%M")
                    except (ValueError, KeyError):
                        time_label = ""
                    entry = {
                        "role": node["role"],
                        "content": node["content"],
                        "time": time_label,
                        "id": node["id"],
                    }
                    if node.get("tool_calls"):
                        fixed_tc = []
                        for tc in node["tool_calls"]:
                            if "id" not in tc:
                                tc = dict(tc, id="")
                            fixed_tc.append(tc)
                        entry["tool_calls"] = fixed_tc
                    if node.get("segments"):
                        entry["segments"] = node["segments"]
                    result.append(entry)
                return result

            return []
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


# 後方互換エイリアス: SessionWindow → TreeSessionWindow
_SessionWindow_old = SessionWindow  # TreeSessionWindow内部から旧クラス参照を保持
SessionWindow = TreeSessionWindow
