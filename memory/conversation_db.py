"""
会話スレッド管理 DB (Nous 版)。

会話を ConversationThread (スレッド) と ConversationTurn (発話) の
2 テーブルで管理する。memory.db とは別ファイル (conversations.db) に保存。

source フィールド: 'discord' | 'mcp' | 'scheduled' | 'webhook' | 'web_ui'
role フィールド: 'user' | 'assistant'

スレッドの新規作成条件:
  - アクティブスレッドが存在しない
  - 最終更新から max_silence_hours 以上経過した
"""

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class ConversationThread:
    id: str
    persona: str
    title: Optional[str] = None
    status: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: Optional[str] = None
    turn_count: int = 0


@dataclass
class ConversationTurn:
    id: int
    thread_id: str
    # 'discord' | 'mcp' | 'scheduled' | 'webhook' | 'web_ui'
    source: str
    channel_id: Optional[str]
    user_id: Optional[str]
    # 'user' | 'assistant'
    role: str
    content: str
    created_at: str
    metadata: dict = field(default_factory=dict)


class ConversationDB:
    """会話スレッドと発話を管理する SQLite ラッパー。

    Args:
        db_path: SQLite ファイルのフルパス (例: data/herta/conversations.db)
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """テーブルとインデックスを作成する。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_threads (
                    id TEXT PRIMARY KEY,
                    persona TEXT NOT NULL,
                    title TEXT DEFAULT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    summary TEXT DEFAULT NULL,
                    turn_count INTEGER DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
                    source TEXT NOT NULL,
                    channel_id TEXT DEFAULT NULL,
                    user_id TEXT DEFAULT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_persona "
                "ON conversation_threads(persona, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_turns_thread "
                "ON conversation_turns(thread_id, created_at)"
            )
            conn.commit()

    # ── スレッド操作 ──────────────────────────────────────────────────────────

    def get_or_create_active_thread(
        self, persona: str, max_silence_hours: float = 8.0
    ) -> ConversationThread:
        """アクティブスレッドを返す。沈黙が長すぎる場合は新規作成する。

        Args:
            persona: ペルソナ名
            max_silence_hours: この時間以上更新がなければ新スレッドを作成

        Returns:
            既存または新規の ConversationThread
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM conversation_threads
                WHERE persona = ? AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (persona,),
            ).fetchone()

        if row:
            thread = self._row_to_thread(row)
            cutoff = datetime.now() - timedelta(hours=max_silence_hours)
            last_updated = datetime.fromisoformat(thread.updated_at)
            if last_updated > cutoff:
                return thread

        return self._create_thread(persona)

    def _create_thread(self, persona: str) -> ConversationThread:
        """新規スレッドを作成して返す。"""
        thread = ConversationThread(id=str(uuid.uuid4()), persona=persona)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversation_threads
                    (id, persona, title, status, created_at, updated_at, turn_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread.id, persona, thread.title, thread.status,
                    thread.created_at, thread.updated_at, 0,
                ),
            )
            conn.commit()
        return thread

    def archive_thread(self, thread_id: str, summary: str) -> None:
        """スレッドをアーカイブして要約を保存する。

        Args:
            thread_id: アーカイブするスレッド ID
            summary: スレッドの要約テキスト
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE conversation_threads
                SET status = 'archived', summary = ?, updated_at = ?
                WHERE id = ?
                """,
                (summary, datetime.now().isoformat(), thread_id),
            )
            conn.commit()

    def list_threads(
        self, persona: str, status: Optional[str] = None
    ) -> List[ConversationThread]:
        """ペルソナのスレッド一覧を返す。

        Args:
            persona: ペルソナ名
            status: フィルタするステータス ('active' | 'archived' | None で全件)

        Returns:
            ConversationThread のリスト (新しい順)
        """
        with sqlite3.connect(self.db_path) as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM conversation_threads
                    WHERE persona = ? AND status = ?
                    ORDER BY updated_at DESC
                    """,
                    (persona, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM conversation_threads
                    WHERE persona = ?
                    ORDER BY updated_at DESC
                    """,
                    (persona,),
                ).fetchall()
        return [self._row_to_thread(r) for r in rows]

    def get_thread(self, thread_id: str) -> Optional[ConversationThread]:
        """スレッド ID でスレッドを取得する。

        Args:
            thread_id: スレッド UUID

        Returns:
            ConversationThread、存在しなければ None
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM conversation_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return self._row_to_thread(row) if row else None

    # ── 発話操作 ──────────────────────────────────────────────────────────────

    def add_turn(
        self,
        thread_id: str,
        source: str,
        role: str,
        content: str,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ConversationTurn:
        """スレッドに発話を追加する。

        スレッドの turn_count と updated_at も同時に更新する。

        Args:
            thread_id: 追加先スレッド ID
            source: 発話ソース ('discord' | 'mcp' | 'scheduled' | 'webhook' | 'web_ui')
            role: 発話者 ('user' | 'assistant')
            content: 発話内容
            channel_id: Discord チャンネル ID など (省略可)
            user_id: ユーザー ID (省略可)
            metadata: 付加情報 dict (省略可)

        Returns:
            作成した ConversationTurn
        """
        now = datetime.now().isoformat()
        meta = metadata or {}

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO conversation_turns
                    (thread_id, source, channel_id, user_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id, source, channel_id, user_id,
                    role, content, now,
                    json.dumps(meta, ensure_ascii=False),
                ),
            )
            turn_id = cur.lastrowid

            conn.execute(
                """
                UPDATE conversation_threads
                SET turn_count = turn_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (now, thread_id),
            )
            conn.commit()

        return ConversationTurn(
            id=turn_id,
            thread_id=thread_id,
            source=source,
            channel_id=channel_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=now,
            metadata=meta,
        )

    def get_recent_turns(
        self, thread_id: str, limit: int = 20
    ) -> List[ConversationTurn]:
        """スレッドの最近の発話を時系列順で返す。

        DB から降順で取得して逆順に並べ直すことで、
        最新 limit 件を古い順に返す。

        Args:
            thread_id: スレッド ID
            limit: 最大取得件数

        Returns:
            ConversationTurn のリスト (古い順)
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation_turns
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()

        turns = []
        for row in reversed(rows):
            meta = json.loads(row[8]) if row[8] else {}
            turns.append(
                ConversationTurn(
                    id=row[0],
                    thread_id=row[1],
                    source=row[2],
                    channel_id=row[3],
                    user_id=row[4],
                    role=row[5],
                    content=row[6],
                    created_at=row[7],
                    metadata=meta,
                )
            )
        return turns

    # ── 内部ヘルパー ──────────────────────────────────────────────────────────

    def _row_to_thread(self, row: tuple) -> ConversationThread:
        """DB 行タプルを ConversationThread に変換する。

        カラム順:
          0 id, 1 persona, 2 title, 3 status,
          4 created_at, 5 updated_at, 6 summary, 7 turn_count
        """
        return ConversationThread(
            id=row[0],
            persona=row[1],
            title=row[2],
            status=row[3],
            created_at=row[4],
            updated_at=row[5],
            summary=row[6],
            turn_count=row[7],
        )
