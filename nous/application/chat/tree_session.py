"""TreeSessionWindow: ツリー構造でメッセージを管理するセッションウィンドウ。"""

from __future__ import annotations

import contextlib
import json
import uuid as _uuid
from datetime import datetime
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.logging.structured import get_logger

from .session_window import _expand_segments

if TYPE_CHECKING:
    import asyncio
    import sqlite3
    from collections.abc import Callable

logger = get_logger(__name__)


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
        self._version: int = 0
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
                result.extend(_expand_segments(segments, ts, now))
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
        return [datetime.fromisoformat(n["created_at"]) for n in self.get_active_path()]

    def update_message(self, message_index: int, new_content: str) -> dict | None:
        """SessionWindow互換: インデックス指定でアクティブパス内のメッセージを編集。"""
        path = self.get_active_path()
        if message_index < 0 or message_index >= len(path):
            return None
        node = path[message_index]
        node["content"] = new_content
        self._version += 1
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
        remove_set = {n["id"] for n in removed}
        # O(n * depth) で子孫を収集
        for other_id, other_node in list(self._nodes.items()):
            if other_id in remove_set:
                continue
            current = other_node.get("parent_id")
            while current is not None:
                if current in remove_set:
                    remove_set.add(other_id)
                    break
                current_node = self._nodes.get(current)
                if current_node is None:
                    break
                current = current_node.get("parent_id")
        remove_ids = remove_set
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
        self._version += 1
        self._persist()
        return removed

    def get_version(self) -> int:
        """現在のバージョンカウンターを返す（楽観的ロック用）。"""
        return self._version

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
        """現在のツリー状態をSQLiteにupsertする。"""
        if self._db is None or not self._persona or not self._session_id:
            return
        try:
            data = {
                "root_id": self._root_id,
                "active_leaf_id": self._active_leaf_id,
                "version": self._version,
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
                # 新形式: {"root_id":..., "active_leaf_id":..., "version":..., "nodes":[...]}
                window._root_id = data.get("root_id")
                window._active_leaf_id = data.get("active_leaf_id")
                window._version = data.get("version", 0)
                for node in data.get("nodes", []):
                    window._nodes[node["id"]] = node
            elif isinstance(data, list):
                # 旧形式: list[dict] — 自動マイグレーション
                timestamps_raw: list[str] = json.loads(row["timestamps"] if hasattr(row, "keys") else row[1])
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
        """メッセージをインプレース編集。segments 内の text も同時に更新。"""
        node = self._nodes.get(msg_id)
        if node is None:
            return None
        node["content"] = new_content
        # segments 内の最初の text タイプセグメントも更新（ツールコールインタリーブ表示用）
        segments = node.get("segments")
        if segments:
            for seg in segments:
                if seg.get("type") == "text":
                    seg["content"] = new_content
                    break
        self._version += 1
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
        # root_id が削除対象ならリペアレンティング後の最初の子を新しいルートに
        if self._root_id == msg_id:
            new_root = None
            for n in self._nodes.values():
                if n.get("parent_id") is None and n["id"] != msg_id:
                    new_root = n["id"]
                    break
            self._root_id = new_root  # 全ノード削除時は None のまま
        del self._nodes[msg_id]
        self._version += 1
        self._persist()
        return node

    def rollback_to(self, msg_id: str) -> dict | None:
        """active_leaf_id を msg_id に差し替え。ノードは一切削除しない（非破壊ロールバック）。"""
        if msg_id not in self._nodes:
            return None
        old = self._active_leaf_id
        self._active_leaf_id = msg_id
        self._version += 1
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
