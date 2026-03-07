"""
Named Memory Blocks (Nous 版)。

MemoryMCP の memory_blocks_db.py を MemoryBlocksDB クラスとして再設計。
「常時コンテキストに載る構造化ブロック」として機能する。

標準ブロック:
  persona_state  - ペルソナの現在の内部状態・気分・進行中の目標
  user_model     - ユーザーについて知っていること・推測
  active_context - 現在のセッションのフォーカス・未解決の問い
"""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import load_config

# 標準ブロック名と説明
STANDARD_BLOCKS: Dict[str, str] = {
    "persona_state": "ペルソナの現在の内部状態・気分・進行中の目標",
    "user_model": "ユーザーについて知っていること・推測（信念・興味・習慣など）",
    "active_context": "現在のセッションのフォーカス・未解決の問い・進行中のトピック",
}


class MemoryBlocksDB:
    """Named Memory Blocks の SQLite ラッパー。

    Args:
        db_path: SQLite ファイルのフルパス (memory.db と共有)
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """memory_blocks テーブルが存在することを確認する。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    description TEXT DEFAULT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(persona, name)
                )
            """)
            conn.commit()

    def _now_iso(self) -> str:
        cfg = load_config()
        tz = cfg.get("timezone", "Asia/Tokyo")
        return datetime.now(ZoneInfo(tz)).isoformat()

    def read(self, persona: str, name: str) -> Optional[str]:
        """ブロックの内容を読み取る。

        Args:
            persona: ペルソナ名
            name: ブロック名 (例: "user_model")

        Returns:
            ブロックの内容文字列、存在しなければ None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT content FROM memory_blocks WHERE persona = ? AND name = ?",
                    (persona, name),
                ).fetchone()
            return row[0] if row else None
        except Exception as e:
            print(f"MemoryBlocksDB.read failed ({name}): {e}")
            return None

    def write(
        self,
        persona: str,
        name: str,
        content: str,
        description: Optional[str] = None,
    ) -> bool:
        """ブロックを書き込む (UPSERT)。

        Args:
            persona: ペルソナ名
            name: ブロック名
            content: ブロックの内容 (既存を置換)
            description: ブロックの説明 (None なら標準説明を使用)

        Returns:
            書き込みに成功した場合 True
        """
        if not name:
            return False

        now = self._now_iso()
        desc = description or STANDARD_BLOCKS.get(name)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO memory_blocks (persona, name, content, description, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(persona, name) DO UPDATE SET
                        content = excluded.content,
                        description = COALESCE(excluded.description, memory_blocks.description),
                        updated_at = excluded.updated_at
                """, (persona, name, content, desc, now))
                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryBlocksDB.write failed ({name}): {e}")
            return False

    def delete(self, persona: str, name: str) -> bool:
        """ブロックを削除する。

        Args:
            persona: ペルソナ名
            name: ブロック名

        Returns:
            削除に成功した場合 True
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM memory_blocks WHERE persona = ? AND name = ?",
                    (persona, name),
                )
                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryBlocksDB.delete failed ({name}): {e}")
            return False

    def list_all(self, persona: str) -> List[Dict[str, Any]]:
        """ペルソナの全ブロックを返す。

        Args:
            persona: ペルソナ名

        Returns:
            [{"name": ..., "content": ..., "description": ..., "updated_at": ...}, ...]
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT name, content, description, updated_at
                    FROM memory_blocks
                    WHERE persona = ?
                    ORDER BY name
                    """,
                    (persona,),
                ).fetchall()
            return [
                {
                    "name": r[0],
                    "content": r[1],
                    "description": r[2],
                    "updated_at": r[3],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"MemoryBlocksDB.list_all failed: {e}")
            return []
