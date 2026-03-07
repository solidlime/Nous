"""
MemoryMCP → Nous データ移行スクリプト。

使い方:
    python -m migrations.memorymcp_to_nous --source /path/to/memorymcp/data --target ./data --persona herta

概要:
- 旧 MemoryMCP の memories テーブルを Nous の schema に変換
- MemoryBlock, UserState も移行
- ベクトルストアは Nous 側で再構築（Qdrant コレクション名も変わるため）
- 旧データは変更しない（読み取り専用で使用）
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── 旧スキーマ定義 ───────────────────────────────────────────────────────────

OLD_MEMORIES_COLUMNS = [
    "id", "key", "content", "importance", "tags", "source", "privacy_level",
    "created_at", "updated_at", "access_count", "last_accessed",
    "memory_type", "associations", "context", "emotional_tone",
    "recall_strength", "metadata",
]

# ── 移行ロジック ─────────────────────────────────────────────────────────────


def migrate(
    source_dir: str,
    target_dir: str,
    persona: str,
    dry_run: bool = False,
    skip_vector_rebuild: bool = False,
) -> dict:
    """
    MemoryMCP データを Nous 形式に移行する。

    Args:
        source_dir: 旧 MemoryMCP の data/{persona}/ ディレクトリ
        target_dir: Nous の data/ ルートディレクトリ
        persona: ペルソナ名
        dry_run: True なら実際の書き込みをしない
        skip_vector_rebuild: True ならベクトルストア再構築をスキップ

    Returns:
        移行結果の統計情報
    """
    source_path = Path(source_dir)
    target_persona_dir = Path(target_dir) / persona

    # 旧 DB パス（MemoryMCP のデフォルト構造に合わせる）
    old_db_candidates = [
        source_path / "memory.db",
        source_path / persona / "memory.db",
        source_path / f"{persona}.db",
    ]
    old_db_path = None
    for c in old_db_candidates:
        if c.exists():
            old_db_path = c
            break

    if old_db_path is None:
        logger.error(f"旧 DB が見つからないよ。試したパス: {old_db_candidates}")
        return {"success": False, "error": "source DB not found"}

    logger.info(f"移行元: {old_db_path}")
    logger.info(f"移行先: {target_persona_dir}")

    if not dry_run:
        target_persona_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "memories_migrated": 0,
        "memories_skipped": 0,
        "blocks_migrated": 0,
        "user_state_migrated": 0,
        "errors": [],
    }

    # ── 記憶の移行 ─────────────────────────────────────────────────────────

    new_db_path = target_persona_dir / "memory.db"
    logger.info("記憶を移行中...")

    _migrate_memories(old_db_path, new_db_path, persona, dry_run, stats)

    # ── MemoryBlocks の移行 ─────────────────────────────────────────────────

    logger.info("Memory Blocks を移行中...")
    _migrate_blocks(old_db_path, new_db_path, dry_run, stats)

    # ── UserState の移行 ───────────────────────────────────────────────────

    logger.info("User State を移行中...")
    _migrate_user_state(old_db_path, new_db_path, dry_run, stats)

    # ── ベクトルストア再構築 ────────────────────────────────────────────────

    if not skip_vector_rebuild and not dry_run:
        logger.info("ベクトルストアを再構築中（時間がかかるよ）...")
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from memory.vector_store import VectorStore
            vs = VectorStore(persona)
            count = vs.rebuild(str(new_db_path))
            logger.info(f"ベクトルストア再構築完了: {count} 件")
            stats["vectors_rebuilt"] = count
        except Exception as e:
            logger.warning(f"ベクトルストア再構築をスキップ: {e}")
            stats["vector_rebuild_skipped"] = str(e)

    logger.info(f"移行完了: {stats}")
    return {"success": True, **stats}


def _migrate_memories(
    old_db_path: Path,
    new_db_path: Path,
    persona: str,
    dry_run: bool,
    stats: dict,
) -> None:
    """旧 memories テーブルを新スキーマに変換して書き込む。"""
    old_conn = sqlite3.connect(str(old_db_path))
    old_conn.row_factory = sqlite3.Row

    try:
        # 旧テーブルのカラムを確認
        cursor = old_conn.execute("PRAGMA table_info(memories)")
        columns = {row["name"] for row in cursor.fetchall()}
        logger.info(f"旧 memories カラム: {columns}")

        rows = old_conn.execute("SELECT * FROM memories").fetchall()
        logger.info(f"移行対象記憶: {len(rows)} 件")

        if dry_run:
            logger.info(f"[DRY RUN] {len(rows)} 件の記憶を移行する予定")
            stats["memories_migrated"] = len(rows)
            return

        # 新 DB を初期化
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from memory.db import MemoryDB
        new_db = MemoryDB(str(new_db_path))

        for row in rows:
            try:
                # 旧 → 新 マッピング
                d = dict(row)

                # tags: JSON 文字列 → Python list
                tags = d.get("tags", "[]")
                if isinstance(tags, str):
                    try:
                        tags = json.loads(tags)
                    except Exception:
                        tags = [t.strip() for t in tags.split(",") if t.strip()]

                # associations: JSON → list
                associations = d.get("associations", "[]")
                if isinstance(associations, str):
                    try:
                        associations = json.loads(associations)
                    except Exception:
                        associations = []

                # metadata: JSON → dict
                metadata = d.get("metadata", "{}")
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}

                # MemoryEntry 互換の insert
                new_conn = sqlite3.connect(str(new_db_path))
                try:
                    new_conn.execute("""
                        INSERT OR IGNORE INTO memories (
                            key, content, importance, tags, source,
                            privacy_level, created_at, updated_at,
                            access_count, last_accessed, memory_type,
                            associations, context, emotional_tone,
                            recall_strength, metadata,
                            elevated, elevation_at, elevation_narrative,
                            elevation_emotion, elevation_significance,
                            is_active
                        ) VALUES (
                            ?, ?, ?, ?, ?,
                            ?, ?, ?,
                            ?, ?, ?,
                            ?, ?, ?,
                            ?, ?,
                            0, NULL, NULL,
                            NULL, NULL,
                            1
                        )
                    """, (
                        d.get("key", str(uuid.uuid4())),
                        d.get("content", ""),
                        d.get("importance", 0.5),
                        json.dumps(tags, ensure_ascii=False),
                        d.get("source", "migration"),
                        d.get("privacy_level", "internal"),
                        d.get("created_at", datetime.now().isoformat()),
                        d.get("updated_at", datetime.now().isoformat()),
                        d.get("access_count", 0),
                        d.get("last_accessed"),
                        d.get("memory_type", "general"),
                        json.dumps(associations, ensure_ascii=False),
                        d.get("context", ""),
                        d.get("emotional_tone", "neutral"),
                        d.get("recall_strength", 1.0),
                        json.dumps(metadata, ensure_ascii=False),
                    ))
                    new_conn.commit()
                    stats["memories_migrated"] += 1
                except Exception as e:
                    stats["errors"].append(f"key={d.get('key')}: {e}")
                    stats["memories_skipped"] += 1
                finally:
                    new_conn.close()

            except Exception as e:
                stats["errors"].append(f"row error: {e}")
                stats["memories_skipped"] += 1

    finally:
        old_conn.close()


def _migrate_blocks(old_db_path: Path, new_db_path: Path, dry_run: bool, stats: dict) -> None:
    """memory_blocks テーブルを移行する。"""
    old_conn = sqlite3.connect(str(old_db_path))
    try:
        # テーブル存在チェック
        tables = {
            row[0]
            for row in old_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "memory_blocks" not in tables:
            logger.info("memory_blocks テーブルなし。スキップ。")
            return

        rows = old_conn.execute("SELECT * FROM memory_blocks").fetchall()
        logger.info(f"移行対象 blocks: {len(rows)} 件")

        if dry_run:
            stats["blocks_migrated"] = len(rows)
            return

        new_conn = sqlite3.connect(str(new_db_path))
        try:
            for row in rows:
                try:
                    new_conn.execute(
                        "INSERT OR REPLACE INTO memory_blocks (name, content, updated_at, metadata)"
                        " VALUES (?, ?, ?, ?)",
                        (row[0], row[1], row[2], row[3] if len(row) > 3 else "{}"),
                    )
                    stats["blocks_migrated"] += 1
                except Exception as e:
                    stats["errors"].append(f"block error: {e}")
            new_conn.commit()
        finally:
            new_conn.close()
    except Exception as e:
        logger.warning(f"blocks 移行エラー: {e}")
    finally:
        old_conn.close()


def _migrate_user_state(old_db_path: Path, new_db_path: Path, dry_run: bool, stats: dict) -> None:
    """user_states テーブルを移行する。"""
    old_conn = sqlite3.connect(str(old_db_path))
    try:
        tables = {
            row[0]
            for row in old_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "user_states" not in tables:
            logger.info("user_states テーブルなし。スキップ。")
            return

        rows = old_conn.execute("SELECT * FROM user_states").fetchall()
        logger.info(f"移行対象 user_states: {len(rows)} 件")

        if dry_run:
            stats["user_state_migrated"] = len(rows)
            return

        new_conn = sqlite3.connect(str(new_db_path))
        try:
            for row in rows:
                try:
                    new_conn.execute(
                        "INSERT OR REPLACE INTO user_states VALUES (?, ?, ?, ?, ?)",
                        row[:5],
                    )
                    stats["user_state_migrated"] += 1
                except Exception as e:
                    stats["errors"].append(f"user_state error: {e}")
            new_conn.commit()
        finally:
            new_conn.close()
    except Exception as e:
        logger.warning(f"user_state 移行エラー: {e}")
    finally:
        old_conn.close()


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MemoryMCP → Nous データ移行ツール")
    parser.add_argument("--source", required=True, help="旧 MemoryMCP の data/ ディレクトリ")
    parser.add_argument("--target", default="./data", help="Nous の data/ ルート")
    parser.add_argument("--persona", default="herta", help="ペルソナ名")
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（書き込みなし）")
    parser.add_argument("--skip-vector-rebuild", action="store_true", help="ベクトル再構築スキップ")
    args = parser.parse_args()

    result = migrate(
        source_dir=args.source,
        target_dir=args.target,
        persona=args.persona,
        dry_run=args.dry_run,
        skip_vector_rebuild=args.skip_vector_rebuild,
    )

    if result.get("success"):
        print(f"\n✅ 移行成功!")
        print(f"  記憶: {result.get('memories_migrated', 0)} 件")
        print(f"  ブロック: {result.get('blocks_migrated', 0)} 件")
        print(f"  ユーザー状態: {result.get('user_state_migrated', 0)} 件")
        if result.get("vectors_rebuilt"):
            print(f"  ベクトル: {result['vectors_rebuilt']} 件")
        if result.get("errors"):
            print(f"\n⚠️  エラー ({len(result['errors'])} 件):")
            for e in result["errors"][:10]:
                print(f"  - {e}")
    else:
        print(f"\n❌ 移行失敗: {result.get('error')}")
        sys.exit(1)
