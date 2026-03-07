"""
Nous memory データベース操作モジュール。

MemoryMCP の memory_db.py を MemoryDB クラスとして再設計。
昇華フィールド (elevated / elevation_at / elevation_narrative /
elevation_emotion / elevation_significance) を追加した 24 カラム構成。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from memory.schema import MemoryEntry


class MemoryDB:
    """ペルソナ別 SQLite memory DB ラッパー。

    Args:
        db_path: SQLite ファイルのフルパス (例: data/herta/memory.db)
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ── 初期化 ────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """テーブルを作成し、WAL モードを有効にする。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")

            # 記憶エントリ本体 (24 カラム)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tags TEXT,
                    importance REAL DEFAULT 0.5,
                    emotion TEXT DEFAULT 'neutral',
                    emotion_intensity REAL DEFAULT 0.0,
                    physical_state TEXT DEFAULT 'normal',
                    mental_state TEXT DEFAULT 'calm',
                    environment TEXT DEFAULT 'unknown',
                    relationship_status TEXT DEFAULT 'normal',
                    action_tag TEXT DEFAULT NULL,
                    related_keys TEXT DEFAULT '[]',
                    summary_ref TEXT DEFAULT NULL,
                    equipped_items TEXT DEFAULT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TEXT DEFAULT NULL,
                    privacy_level TEXT DEFAULT 'internal',
                    elevated INTEGER DEFAULT 0,
                    elevation_at TEXT DEFAULT NULL,
                    elevation_narrative TEXT DEFAULT NULL,
                    elevation_emotion TEXT DEFAULT NULL,
                    elevation_significance REAL DEFAULT NULL
                )
            """)

            # Ebbinghaus 忘却曲線: strength = importance * e^(-t/S)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_strength (
                    key TEXT PRIMARY KEY,
                    strength REAL DEFAULT 0.5,
                    stability REAL DEFAULT 1.0,
                    last_decay_at TEXT,
                    FOREIGN KEY (key) REFERENCES memories(key) ON DELETE CASCADE
                )
            """)

            # 操作ログ
            conn.execute("""
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    key TEXT,
                    before TEXT,
                    after TEXT,
                    success INTEGER NOT NULL,
                    error TEXT,
                    metadata TEXT
                )
            """)

            # 身体感覚履歴 (時系列可視化用)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS physical_sensations_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    memory_key TEXT,
                    fatigue REAL DEFAULT 0.0,
                    warmth REAL DEFAULT 0.5,
                    arousal REAL DEFAULT 0.0,
                    touch_response TEXT DEFAULT 'normal',
                    heart_rate_metaphor TEXT DEFAULT 'calm',
                    FOREIGN KEY (memory_key) REFERENCES memories(key) ON DELETE SET NULL
                )
            """)

            # 感情履歴 (時系列可視化用)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    memory_key TEXT,
                    emotion TEXT NOT NULL,
                    emotion_intensity REAL DEFAULT 0.0,
                    FOREIGN KEY (memory_key) REFERENCES memories(key) ON DELETE SET NULL
                )
            """)

            conn.commit()

    # ── 書き込み ──────────────────────────────────────────────────────────────

    def save(self, entry: MemoryEntry) -> bool:
        """記憶エントリを保存 (INSERT OR REPLACE)。

        Args:
            entry: 保存する MemoryEntry

        Returns:
            保存に成功した場合 True
        """
        try:
            tags_json = json.dumps(entry.tags, ensure_ascii=False) if entry.tags else None
            related_json = json.dumps(entry.related_keys, ensure_ascii=False)
            equipped_json = (
                json.dumps(entry.equipped_items, ensure_ascii=False)
                if entry.equipped_items
                else None
            )

            # 重要度・感情強度は 0.0–1.0 に clamp する
            importance = max(0.0, min(1.0, entry.importance))
            emotion_intensity = max(0.0, min(1.0, entry.emotion_intensity))

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO memories (
                        key, content, created_at, updated_at,
                        tags, importance, emotion, emotion_intensity,
                        physical_state, mental_state, environment, relationship_status,
                        action_tag, related_keys, summary_ref, equipped_items,
                        access_count, last_accessed, privacy_level,
                        elevated, elevation_at, elevation_narrative,
                        elevation_emotion, elevation_significance
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?,
                        ?, ?
                    )
                """, (
                    entry.key, entry.content, entry.created_at, entry.updated_at,
                    tags_json, importance, entry.emotion, emotion_intensity,
                    entry.physical_state, entry.mental_state, entry.environment,
                    entry.relationship_status, entry.action_tag, related_json,
                    entry.summary_ref, equipped_json,
                    entry.access_count, entry.last_accessed, entry.privacy_level,
                    1 if entry.elevated else 0,
                    entry.elevation_at, entry.elevation_narrative,
                    entry.elevation_emotion, entry.elevation_significance,
                ))

                # memory_strength テーブルへの初期行挿入 (存在しない場合のみ)
                conn.execute("""
                    INSERT OR IGNORE INTO memory_strength (key, strength, stability, last_decay_at)
                    VALUES (?, ?, 1.0, ?)
                """, (entry.key, importance, entry.created_at))

                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryDB.save failed ({entry.key}): {e}")
            return False

    def delete(self, key: str) -> bool:
        """指定キーの記憶を削除する。

        Args:
            key: 削除する記憶キー

        Returns:
            削除に成功した場合 True
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM memories WHERE key = ?", (key,))
                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryDB.delete failed ({key}): {e}")
            return False

    def increment_access_count(self, key: str) -> bool:
        """アクセスカウントをインクリメントし、last_accessed を更新する。

        Args:
            key: 対象記憶キー

        Returns:
            更新に成功した場合 True
        """
        try:
            now = datetime.now().isoformat()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed = ?
                    WHERE key = ?
                """, (now, key))
                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryDB.increment_access_count failed ({key}): {e}")
            return False

    def update_elevation(
        self,
        key: str,
        narrative: str,
        emotion: str,
        significance: float,
    ) -> bool:
        """昇華情報を更新する。

        Args:
            key: 対象記憶キー
            narrative: LLM が生成した物語的意味付けテキスト
            emotion: 昇華時感情ラベル
            significance: 昇華評価スコア (0.0–1.0)

        Returns:
            更新に成功した場合 True
        """
        try:
            now = datetime.now().isoformat()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE memories
                    SET elevated = 1,
                        elevation_at = ?,
                        elevation_narrative = ?,
                        elevation_emotion = ?,
                        elevation_significance = ?
                    WHERE key = ?
                """, (now, narrative, emotion, significance, key))
                conn.commit()
            return True
        except Exception as e:
            print(f"MemoryDB.update_elevation failed ({key}): {e}")
            return False

    # ── 読み取り ──────────────────────────────────────────────────────────────

    def get_by_key(self, key: str) -> Optional[MemoryEntry]:
        """キーで記憶を取得する。

        Args:
            key: 記憶キー

        Returns:
            MemoryEntry、見つからなければ None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM memories WHERE key = ?", (key,)
                ).fetchone()
            return self._row_to_entry(row) if row else None
        except Exception as e:
            print(f"MemoryDB.get_by_key failed ({key}): {e}")
            return None

    def get_all(self) -> Dict[str, MemoryEntry]:
        """全記憶を {key: MemoryEntry} 形式で返す。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY created_at"
                ).fetchall()
            return {row[0]: self._row_to_entry(row) for row in rows}
        except Exception as e:
            print(f"MemoryDB.get_all failed: {e}")
            return {}

    def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """最近更新された記憶を返す。

        Args:
            limit: 最大取得件数

        Returns:
            MemoryEntry のリスト (新しい順)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        except Exception as e:
            print(f"MemoryDB.get_recent failed: {e}")
            return []

    def search_keyword(self, query: str, limit: int = 20) -> List[MemoryEntry]:
        """SQLite LIKE でキーワード検索する。

        Args:
            query: 検索クエリ
            limit: 最大取得件数

        Returns:
            マッチした MemoryEntry のリスト
        """
        try:
            pattern = f"%{query}%"
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE content LIKE ? OR tags LIKE ?
                    ORDER BY importance DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        except Exception as e:
            print(f"MemoryDB.search_keyword failed: {e}")
            return []

    def get_by_tags(self, tags: List[str]) -> List[MemoryEntry]:
        """指定タグをいずれか含む記憶を返す。

        Args:
            tags: タグ名リスト

        Returns:
            マッチした MemoryEntry のリスト
        """
        if not tags:
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                # タグは JSON 配列として保存されているので LIKE で検索する
                conditions = " OR ".join(["tags LIKE ?"] * len(tags))
                params = [f'%"{t}"%' for t in tags]
                rows = conn.execute(
                    f"SELECT * FROM memories WHERE {conditions} ORDER BY importance DESC",
                    params,
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        except Exception as e:
            print(f"MemoryDB.get_by_tags failed: {e}")
            return []

    def get_unelevated(
        self, min_importance: float = 0.3, limit: int = 10
    ) -> List[MemoryEntry]:
        """昇華未処理の記憶を重要度順に返す。

        Args:
            min_importance: 対象の最低重要度スコア
            limit: 最大取得件数

        Returns:
            MemoryEntry のリスト (重要度降順)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE elevated = 0 AND importance >= ?
                    ORDER BY importance DESC
                    LIMIT ?
                    """,
                    (min_importance, limit),
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]
        except Exception as e:
            print(f"MemoryDB.get_unelevated failed: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """記憶 DB の統計情報を返す。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                elevated = conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE elevated = 1"
                ).fetchone()[0]
                avg_importance = conn.execute(
                    "SELECT AVG(importance) FROM memories"
                ).fetchone()[0]
            return {
                "total": total,
                "elevated": elevated,
                "unelevated": total - elevated,
                "avg_importance": round(avg_importance or 0.0, 3),
            }
        except Exception as e:
            print(f"MemoryDB.get_stats failed: {e}")
            return {"total": 0, "elevated": 0, "unelevated": 0, "avg_importance": 0.0}

    # ── 内部ヘルパー ──────────────────────────────────────────────────────────

    def _row_to_entry(self, row: tuple) -> MemoryEntry:
        """DB の行タプルを MemoryEntry に変換する。

        カラム順:
          0  key, 1  content, 2  created_at, 3  updated_at,
          4  tags, 5  importance, 6  emotion, 7  emotion_intensity,
          8  physical_state, 9  mental_state, 10 environment, 11 relationship_status,
          12 action_tag, 13 related_keys, 14 summary_ref, 15 equipped_items,
          16 access_count, 17 last_accessed, 18 privacy_level,
          19 elevated, 20 elevation_at, 21 elevation_narrative,
          22 elevation_emotion, 23 elevation_significance
        """
        (
            key, content, created_at, updated_at,
            tags_json, importance, emotion, emotion_intensity,
            physical_state, mental_state, environment, relationship_status,
            action_tag, related_keys_json, summary_ref, equipped_items_json,
            access_count, last_accessed, privacy_level,
            elevated_int, elevation_at, elevation_narrative,
            elevation_emotion, elevation_significance,
        ) = row

        return MemoryEntry(
            key=key,
            content=content,
            created_at=created_at,
            updated_at=updated_at,
            tags=json.loads(tags_json) if tags_json else [],
            importance=importance if importance is not None else 0.5,
            emotion=emotion or "neutral",
            emotion_intensity=emotion_intensity if emotion_intensity is not None else 0.0,
            physical_state=physical_state or "normal",
            mental_state=mental_state or "calm",
            environment=environment or "unknown",
            relationship_status=relationship_status or "normal",
            action_tag=action_tag,
            related_keys=json.loads(related_keys_json) if related_keys_json else [],
            summary_ref=summary_ref,
            equipped_items=json.loads(equipped_items_json) if equipped_items_json else None,
            access_count=access_count if access_count is not None else 0,
            last_accessed=last_accessed,
            privacy_level=privacy_level or "internal",
            elevated=bool(elevated_int),
            elevation_at=elevation_at,
            elevation_narrative=elevation_narrative,
            elevation_emotion=elevation_emotion,
            elevation_significance=elevation_significance,
        )

    # ── ユーティリティ ────────────────────────────────────────────────────────

    @staticmethod
    def generate_key() -> str:
        """タイムスタンプベースの記憶キーを生成する。"""
        return f"memory_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def log_operation(
        self,
        operation: str,
        key: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """操作ログを operations テーブルに記録する。"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO operations
                    (timestamp, operation_id, operation, key, before, after, success, error, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    str(uuid.uuid4()),
                    operation,
                    key,
                    json.dumps(before, ensure_ascii=False) if before else None,
                    json.dumps(after, ensure_ascii=False) if after else None,
                    1 if success else 0,
                    error,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ))
                conn.commit()
        except Exception as e:
            print(f"MemoryDB.log_operation failed: {e}")
