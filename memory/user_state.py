"""
Bi-temporal ユーザー状態トラッキング (Nous 版)。

MemoryMCP の user_state_db.py を UserStateDB クラスとして再設計。
user_info フィールドの変更履歴を valid_from / valid_until で管理する。
フィールドを上書きせず、全変更を保持する。

使用例:
    db = UserStateDB("data/herta/memory.db")
    db.update("herta", "name", "らうらう")
    state = db.get_current("herta")   # → {"name": "らうらう", ...}
    history = db.get_history("herta", key="name")
"""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import load_config

# bi-temporal で追跡するフィールド名セット
USER_STATE_KEYS = {"name", "nickname", "preferred_address"}


class UserStateDB:
    """bi-temporal ユーザー状態の SQLite ラッパー。

    Args:
        db_path: SQLite ファイルのフルパス (memory.db と共有)
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """user_state_history テーブルが存在することを確認する。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_state_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_state_persona_key
                ON user_state_history(persona, key, valid_until)
            """)
            conn.commit()

    def _now_iso(self) -> str:
        cfg = load_config()
        tz = cfg.get("timezone", "Asia/Tokyo")
        return datetime.now(ZoneInfo(tz)).isoformat()

    def update(self, persona: str, key: str, value: str) -> bool:
        """ユーザー状態を bi-temporal に更新する。

        現在有効なレコードを無効化 (valid_until = now) してから、
        新しいレコードを挿入する。

        Args:
            persona: ペルソナ名
            key: 状態キー (例: "name", "nickname")
            value: 新しい値

        Returns:
            更新に成功した場合 True
        """
        now = self._now_iso()
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 現在有効なレコードを無効化
                conn.execute("""
                    UPDATE user_state_history
                    SET valid_until = ?
                    WHERE persona = ? AND key = ? AND valid_until IS NULL
                """, (now, persona, key))

                # 新レコードを挿入
                conn.execute("""
                    INSERT INTO user_state_history
                        (persona, key, value, valid_from, valid_until, created_at)
                    VALUES (?, ?, ?, ?, NULL, ?)
                """, (persona, key, value, now, now))
                conn.commit()
            return True
        except Exception as e:
            print(f"UserStateDB.update failed ({key}={value!r}): {e}")
            return False

    def update_bulk(self, persona: str, fields: Dict[str, str]) -> int:
        """複数フィールドをまとめて更新する。

        Args:
            persona: ペルソナ名
            fields: {key: value} の dict

        Returns:
            更新したフィールド数
        """
        updated = 0
        for key, value in fields.items():
            if key in USER_STATE_KEYS and value is not None:
                if self.update(persona, key, str(value)):
                    updated += 1
        return updated

    def get_current(self, persona: str) -> Dict[str, str]:
        """現在有効なユーザー状態を {key: value} で返す。

        Args:
            persona: ペルソナ名

        Returns:
            現在有効な全フィールドの dict
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT key, value FROM user_state_history
                    WHERE persona = ? AND valid_until IS NULL
                    ORDER BY key
                """, (persona,)).fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            print(f"UserStateDB.get_current failed: {e}")
            return {}

    def get_history(
        self,
        persona: str,
        key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """ユーザー状態の変更履歴を返す。

        Args:
            persona: ペルソナ名
            key: 特定フィールドでフィルタ (None なら全フィールド)

        Returns:
            [{"key": ..., "value": ..., "valid_from": ..., "valid_until": ..., "is_current": bool}, ...]
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                if key:
                    rows = conn.execute("""
                        SELECT key, value, valid_from, valid_until
                        FROM user_state_history
                        WHERE persona = ? AND key = ?
                        ORDER BY valid_from DESC
                    """, (persona, key)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT key, value, valid_from, valid_until
                        FROM user_state_history
                        WHERE persona = ?
                        ORDER BY key, valid_from DESC
                    """, (persona,)).fetchall()

            return [
                {
                    "key": r[0],
                    "value": r[1],
                    "valid_from": r[2],
                    "valid_until": r[3],
                    "is_current": r[3] is None,
                }
                for r in rows
            ]
        except Exception as e:
            print(f"UserStateDB.get_history failed: {e}")
            return []
