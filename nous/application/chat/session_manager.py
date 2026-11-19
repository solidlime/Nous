"""SessionManager: チャットセッションのライフサイクル管理 + SQLite永続化。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

from .tree_session import TreeSessionWindow

if TYPE_CHECKING:
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
    except Exception as e:
        logger.warning("_cleanup_expired_sessions failed: %s", e)


class SessionManager:
    def __init__(self, max_sessions: int = 100) -> None:
        self._max = max_sessions
        self._sessions: OrderedDict[tuple[str, str], TreeSessionWindow] = OrderedDict()
        # サーバーのイベントループ。窓が握る sqlite 接続はスレッド親和性を持つので、
        # ワーカースレッドからの追記はここへマーシャルする (kanban #86)。
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """このマネージャを所有するイベントループを登録する（起動時に1回）。"""
        self._loop = loop

    def append(
        self,
        persona: str,
        session_id: str,
        role: str,
        content: str,
        max_messages: int = 200,
        db_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        """別スレッドからでも安全な追記。

        窓の ``_persist`` は生成時のスレッドの sqlite 接続を使うので、ワーカー
        スレッドから直接 ``add`` すると ``ProgrammingError`` になり、記録が
        無言で落ちる。ループが束縛されていて現在地と違えば、サーバーループへ
        委譲してから追記する。接続は呼び出し元のスレッドで作ってはいけないので
        ``db_factory`` を渡し、追記するスレッドで解决する。
        """

        def _apply() -> None:
            db = db_factory() if db_factory is not None else None
            self.get_or_create(persona, session_id, max_messages=max_messages, db=db).add(role, content)

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if self._loop is None or current is self._loop or not self._loop.is_running():
            _apply()
            return

        async def _run() -> None:
            _apply()

        try:
            asyncio.run_coroutine_threadsafe(_run(), self._loop).result(timeout=10)
        except Exception:
            logger.warning("SessionManager.append: cross-thread append failed", exc_info=True)

    def get_or_create(
        self,
        persona: str,
        session_id: str,
        max_messages: int = 200,
        db: sqlite3.Connection | None = None,
    ) -> TreeSessionWindow:
        """同期関数。``await`` を挟むと check-then-set の窓ができるので、ここに
        ``await`` を入れないこと（呼び出し元は同一イベントループのコルーチンのみ）。
        """
        key = (persona, session_id)
        if key in self._sessions:
            self._sessions.move_to_end(key)
            window = self._sessions[key]
            # max_messages 変更を同期
            if window._max_messages != max_messages:
                window._max_messages = max_messages
                # 減った場合は超過分を即座に evict
                path_len = window.get_message_count()
                if path_len > max_messages:
                    overflow = path_len - max_messages
                    evicted = window._evict_oldest(overflow)
                    if evicted and window.evict_callback is not None:
                        with contextlib.suppress(Exception):
                            window.evict_callback(evicted)
            return window
        if len(self._sessions) >= self._max:
            self._sessions.popitem(last=False)

        created: TreeSessionWindow | None = None
        if db is not None:
            try:
                db.execute(_CHAT_SESSIONS_SCHEMA)
            except Exception as _e:
                logger.warning("SessionStore: failed to init DB schema: %s", _e)
            created = TreeSessionWindow.from_db(db, persona, session_id, max_messages)
            if created is None:
                created = TreeSessionWindow(max_messages=max_messages)
                created.attach_db(db, persona, session_id)
                _cleanup_expired_sessions(db, persona)
        else:
            created = TreeSessionWindow(max_messages=max_messages)

        self._sessions[key] = created
        return created

    def clear(self, persona: str, session_id: str) -> None:
        from nous.application.chat.skills_state import clear_session

        clear_session(persona, session_id)
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
            messages_raw = row[0] if not hasattr(row, "keys") else row["messages"]
            data = json.loads(messages_raw)

            # 旧形式: list[dict] — 従来の処理
            if isinstance(data, list):
                timestamps_raw: list[str] = json.loads(row[1] if not hasattr(row, "keys") else row["timestamps"])
                result: list[dict] = []
                for msg, ts_str in zip(data, timestamps_raw, strict=False):
                    try:
                        dt = datetime.fromisoformat(ts_str)
                        time_label = dt.strftime("%H:%M")
                    except ValueError:
                        time_label = ""
                    entry: dict[str, object] = {
                        "role": msg["role"],
                        "content": msg["content"],
                        "time": time_label,
                        "ts": ts_str,
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
                        "ts": node.get("created_at", ""),
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
            return True
        except Exception as e:
            logger.warning("SessionManager.delete_session failed: %s", e)
            return False
