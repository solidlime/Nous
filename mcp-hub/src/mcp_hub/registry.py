"""
MCP サーバー登録の永続化レイヤー。
テーブル: servers (name TEXT PRIMARY KEY, config_json TEXT, created_at TEXT)
"""

import json
import os
from datetime import UTC, datetime

import aiosqlite


class SqliteStore:
    """SQLite を使った MCP サーバー登録の永続化。"""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("MCP_HUB_DB_PATH", "data/hub.db")

    async def init(self) -> None:
        """テーブル作成。ディレクトリも自動生成。"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    name TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.commit()

    async def list_servers(self) -> list[dict]:
        """全サーバー取得。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT name, config_json, created_at FROM servers ORDER BY created_at")
            return [
                {
                    "name": row["name"],
                    "config": json.loads(row["config_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    async def add_server(self, name: str, config: dict) -> None:
        """サーバー登録。同名なら上書き。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO servers (name, config_json, created_at) VALUES (?, ?, ?)",
                (name, json.dumps(config), datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def remove_server(self, name: str) -> bool:
        """削除。存在すれば True。"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM servers WHERE name = ?", (name,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_server(self, name: str) -> dict | None:
        """単一取得。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name, config_json, created_at FROM servers WHERE name = ?",
                (name,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "name": row["name"],
                "config": json.loads(row["config_json"]),
                "created_at": row["created_at"],
            }
