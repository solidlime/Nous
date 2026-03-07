"""
Nous MCP 記憶操作ツール。

unified_tools.py を一新した新インターフェース。
ペルソナは Authorization: Bearer {persona} ヘッダーから解決する。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from memory.db import MemoryDB
from memory.blocks import MemoryBlocksDB
from memory.schema import MemoryEntry
from nous_mcp.server import get_persona, get_db_path

logger = logging.getLogger(__name__)


def _get_db(persona: str) -> MemoryDB:
    return MemoryDB(get_db_path(persona))


async def handle_memory(
    operation: str,
    key: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    importance: Optional[float] = None,
    emotion: Optional[str] = None,
    emotion_intensity: Optional[float] = None,
    query: Optional[str] = None,
    search_mode: Optional[str] = "hybrid",
    limit: int = 10,
    block_name: Optional[str] = None,
    block_content: Optional[str] = None,
    persona: str = "herta",
    **kwargs,
) -> str:
    """
    記憶 CRUD + 検索 + ブロック操作。

    operations:
      create, read, update, delete, search, stats,
      block_write, block_read, promise, goal, update_context
    """
    db = _get_db(persona)

    try:
        if operation == "create":
            if not content:
                return json.dumps({"error": "content is required"}, ensure_ascii=False)
            auto_key = key or MemoryDB.generate_key()
            entry = MemoryEntry(
                key=auto_key,
                content=content,
                created_at=_now(),
                updated_at=_now(),
                tags=tags or [],
                importance=importance if importance is not None else 0.5,
                emotion=emotion or "neutral",
                emotion_intensity=emotion_intensity or 0.0,
            )
            success = db.save(entry)
            if success:
                # ベクトルストアにも追加（非同期）
                _try_add_vector(entry, persona)
                return json.dumps({"success": True, "key": auto_key}, ensure_ascii=False)
            return json.dumps({"error": "Failed to save memory"}, ensure_ascii=False)

        elif operation == "read":
            if not key:
                return json.dumps({"error": "key is required for read"}, ensure_ascii=False)
            entry = db.get_by_key(key)
            if entry is None:
                return json.dumps({"error": f"Memory not found: {key}"}, ensure_ascii=False)
            db.increment_access_count(key)
            return json.dumps(_entry_to_dict(entry), ensure_ascii=False, default=str)

        elif operation == "update":
            if not key:
                return json.dumps({"error": "key is required for update"}, ensure_ascii=False)
            entry = db.get_by_key(key)
            if entry is None:
                return json.dumps({"error": f"Memory not found: {key}"}, ensure_ascii=False)
            if content is not None:
                entry.content = content
            if tags is not None:
                entry.tags = tags
            if importance is not None:
                entry.importance = importance
            if emotion is not None:
                entry.emotion = emotion
            if emotion_intensity is not None:
                entry.emotion_intensity = emotion_intensity
            entry.updated_at = _now()
            success = db.save(entry)
            if success:
                _try_update_vector(entry, persona)
            return json.dumps({"success": success, "key": key}, ensure_ascii=False)

        elif operation == "delete":
            if not key:
                return json.dumps({"error": "key is required for delete"}, ensure_ascii=False)
            success = db.delete(key)
            if success:
                _try_delete_vector(key, persona)
            return json.dumps({"success": success, "key": key}, ensure_ascii=False)

        elif operation == "search":
            if not query:
                return json.dumps({"error": "query is required for search"}, ensure_ascii=False)
            results = _search(db, query, search_mode or "hybrid", limit, persona)
            return json.dumps({
                "results": [_entry_to_dict(e) for e in results],
                "count": len(results),
                "mode": search_mode,
            }, ensure_ascii=False, default=str)

        elif operation == "stats":
            stats = db.get_stats()
            return json.dumps(stats, ensure_ascii=False, default=str)

        elif operation == "block_write":
            if not block_name or block_content is None:
                return json.dumps({"error": "block_name and block_content are required"}, ensure_ascii=False)
            blocks_db = MemoryBlocksDB(get_db_path(persona))
            blocks_db.write_block(persona, block_name, block_content)
            return json.dumps({"success": True, "block": block_name}, ensure_ascii=False)

        elif operation == "block_read":
            blocks_db = MemoryBlocksDB(get_db_path(persona))
            if block_name:
                block = blocks_db.get_block(persona, block_name)
                return json.dumps({"block": block_name, "content": block}, ensure_ascii=False) if block else json.dumps({"error": f"Block not found: {block_name}"}, ensure_ascii=False)
            else:
                all_blocks = blocks_db.get_all_blocks(persona)
                return json.dumps({"blocks": all_blocks}, ensure_ascii=False)

        elif operation == "promise":
            # promise は tags=['promise'] + metadata で保存
            if not content:
                return json.dumps({"error": "content is required for promise"}, ensure_ascii=False)
            promise_key = key or f"promise_{_now_compact()}"
            entry = MemoryEntry(
                key=promise_key,
                content=content,
                created_at=_now(),
                updated_at=_now(),
                tags=(tags or []) + ["promise"],
                importance=importance if importance is not None else 0.7,
            )
            success = db.save(entry)
            return json.dumps({"success": success, "key": promise_key}, ensure_ascii=False)

        elif operation == "goal":
            if not content:
                return json.dumps({"error": "content is required for goal"}, ensure_ascii=False)
            goal_key = key or f"goal_{_now_compact()}"
            entry = MemoryEntry(
                key=goal_key,
                content=content,
                created_at=_now(),
                updated_at=_now(),
                tags=(tags or []) + ["goal"],
                importance=importance if importance is not None else 0.7,
            )
            success = db.save(entry)
            return json.dumps({"success": success, "key": goal_key}, ensure_ascii=False)

        elif operation == "update_context":
            # persona context 更新
            from memory.persona import PersonaContext
            from config import get_config as _cfg
            cfg = _cfg()
            data_dir = cfg.get("data_dir", "data")
            ctx_path = f"{data_dir}/{persona}/persona_context.json"
            ctx = PersonaContext(ctx_path)
            if content:
                ctx.update(json.loads(content) if isinstance(content, str) else content)
            return json.dumps({"success": True}, ensure_ascii=False)

        else:
            return json.dumps({"error": f"Unknown operation: {operation}"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"memory({operation}) error: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _entry_to_dict(entry: MemoryEntry) -> Dict[str, Any]:
    return {
        "key": entry.key,
        "content": entry.content,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "tags": entry.tags,
        "importance": entry.importance,
        "emotion": entry.emotion,
        "emotion_intensity": entry.emotion_intensity,
        "physical_state": entry.physical_state,
        "mental_state": entry.mental_state,
        "access_count": entry.access_count,
        "privacy_level": entry.privacy_level,
        "elevated": entry.elevated,
        "elevation_narrative": entry.elevation_narrative,
        "elevation_emotion": entry.elevation_emotion,
        "elevation_significance": entry.elevation_significance,
    }


def _search(db: MemoryDB, query: str, mode: str, limit: int, persona: str) -> List[MemoryEntry]:
    """検索モードに応じて検索を実行する。"""
    if mode == "keyword":
        return db.search_keyword(query, limit=limit)
    elif mode == "semantic":
        return _semantic_search(query, limit, persona)
    elif mode in ("hybrid", "smart"):
        # RRF (Reciprocal Rank Fusion) - keyword + semantic
        keyword_results = db.search_keyword(query, limit=limit)
        semantic_results = _semantic_search(query, limit, persona)
        return _rrf_merge(keyword_results, semantic_results, limit)
    else:
        return db.search_keyword(query, limit=limit)


def _semantic_search(query: str, limit: int, persona: str) -> List[MemoryEntry]:
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        return vs.search(query, limit=limit)
    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        return []


def _rrf_merge(list_a: List[MemoryEntry], list_b: List[MemoryEntry], limit: int) -> List[MemoryEntry]:
    """Reciprocal Rank Fusion で2つのリストをマージ。"""
    k = 60
    scores: Dict[str, float] = {}
    order: Dict[str, MemoryEntry] = {}
    for rank, entry in enumerate(list_a):
        scores[entry.key] = scores.get(entry.key, 0.0) + 1.0 / (k + rank + 1)
        order[entry.key] = entry
    for rank, entry in enumerate(list_b):
        scores[entry.key] = scores.get(entry.key, 0.0) + 1.0 / (k + rank + 1)
        order[entry.key] = entry
    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [order[k] for k in sorted_keys[:limit]]


def _try_add_vector(entry: MemoryEntry, persona: str) -> None:
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        vs.add(entry)
    except Exception as e:
        logger.debug(f"Vector add skipped: {e}")


def _try_update_vector(entry: MemoryEntry, persona: str) -> None:
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        vs.update(entry)
    except Exception as e:
        logger.debug(f"Vector update skipped: {e}")


def _try_delete_vector(key: str, persona: str) -> None:
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        vs.delete(key)
    except Exception as e:
        logger.debug(f"Vector delete skipped: {e}")


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


def _now_compact() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d%H%M%S")


def register_memory_tools(mcp) -> None:
    """FastMCP に記憶ツールを登録する。"""

    @mcp.tool()
    async def memory(
        operation: str,
        key: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: Optional[float] = None,
        emotion: Optional[str] = None,
        emotion_intensity: Optional[float] = None,
        query: Optional[str] = None,
        search_mode: Optional[str] = "hybrid",
        limit: int = 10,
        block_name: Optional[str] = None,
        block_content: Optional[str] = None,
    ) -> str:
        """
        記憶の CRUD・検索・ブロック操作。

        operation:
          create  — 新しい記憶を作成
          read    — key で記憶を取得
          update  — 記憶を更新
          delete  — 記憶を削除
          search  — クエリで記憶を検索 (search_mode: keyword/semantic/hybrid/smart)
          stats   — 記憶統計を返す
          block_write — Named Memory Block に書き込む
          block_read  — Named Memory Block を読む
          promise — 約束として記憶する
          goal    — 目標として記憶する
          update_context — ペルソナコンテキストを更新
        """
        persona = get_persona()
        return await handle_memory(
            operation=operation,
            key=key,
            content=content,
            tags=tags,
            importance=importance,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
            query=query,
            search_mode=search_mode,
            limit=limit,
            block_name=block_name,
            block_content=block_content,
            persona=persona,
        )
