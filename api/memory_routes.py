"""
Nous 記憶 REST API ルーター。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from memory.db import MemoryDB
from memory.schema import MemoryEntry
from nous_mcp.server import get_persona, get_db_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memories", tags=["memories"])


# ── リクエストモデル ─────────────────────────────────────────────────────────


class MemoryCreateRequest(BaseModel):
    key: Optional[str] = None
    content: str
    tags: List[str] = []
    importance: float = 0.5
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    privacy_level: str = "internal"


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    importance: Optional[float] = None
    emotion: Optional[str] = None
    emotion_intensity: Optional[float] = None
    privacy_level: Optional[str] = None


class MemorySearchRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # keyword | semantic | hybrid | smart
    limit: int = 10
    min_importance: Optional[float] = None
    tags: Optional[List[str]] = None


# ── ヘルパー ────────────────────────────────────────────────────────────────


def _get_db(request: Request) -> MemoryDB:
    persona = get_persona(request)
    return MemoryDB(get_db_path(persona))


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


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


# ── エンドポイント ───────────────────────────────────────────────────────────


@router.get("")
async def list_memories(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("recent"),
    min_importance: Optional[float] = Query(None),
    tags: Optional[str] = Query(None),
):
    """記憶一覧取得（ページネーション対応）。"""
    db = _get_db(request)
    try:
        all_entries = db.get_recent(limit=limit + offset)
        tag_filter = [t.strip() for t in tags.split(",")] if tags else None
        if tag_filter:
            all_entries = [e for e in all_entries if any(t in e.tags for t in tag_filter)]
        if min_importance is not None:
            all_entries = [e for e in all_entries if e.importance >= min_importance]
        paginated = all_entries[offset : offset + limit]
        stats = db.get_stats()
        return {
            "memories": [_entry_to_dict(e) for e in paginated],
            "total": stats.get("total_count", 0),
            "elevated": stats.get("elevated_count", 0),
            "avg_importance": stats.get("avg_importance", 0.0),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"list_memories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_memory(request: Request, body: MemoryCreateRequest):
    """新しい記憶を作成する。"""
    db = _get_db(request)
    persona = get_persona(request)
    try:
        key = body.key or MemoryDB.generate_key()
        entry = MemoryEntry(
            key=key,
            content=body.content,
            created_at=_now(),
            updated_at=_now(),
            tags=body.tags,
            importance=body.importance,
            emotion=body.emotion,
            emotion_intensity=body.emotion_intensity,
            privacy_level=body.privacy_level,
        )
        success = db.save(entry)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save memory")
        # ベクトルストアに追加（バックグラウンド）
        try:
            from memory.vector_store import VectorStore
            vs = VectorStore(persona)
            vs.add(entry)
        except Exception:
            pass
        return JSONResponse(status_code=201, content={"key": key, "success": True})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{key}")
async def get_memory(key: str, request: Request):
    """キーで記憶を取得する。"""
    db = _get_db(request)
    entry = db.get_by_key(key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Memory not found: {key}")
    db.increment_access_count(key)
    return _entry_to_dict(entry)


@router.put("/{key}")
async def update_memory(key: str, request: Request, body: MemoryUpdateRequest):
    """記憶を更新する。"""
    db = _get_db(request)
    persona = get_persona(request)
    entry = db.get_by_key(key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Memory not found: {key}")
    if body.content is not None:
        entry.content = body.content
    if body.tags is not None:
        entry.tags = body.tags
    if body.importance is not None:
        entry.importance = body.importance
    if body.emotion is not None:
        entry.emotion = body.emotion
    if body.emotion_intensity is not None:
        entry.emotion_intensity = body.emotion_intensity
    if body.privacy_level is not None:
        entry.privacy_level = body.privacy_level
    entry.updated_at = _now()
    success = db.save(entry)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update memory")
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        vs.update(entry)
    except Exception:
        pass
    return {"key": key, "success": True}


@router.delete("/{key}")
async def delete_memory(key: str, request: Request):
    """記憶を削除する。"""
    db = _get_db(request)
    persona = get_persona(request)
    entry = db.get_by_key(key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Memory not found: {key}")
    success = db.delete(key)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete memory")
    try:
        from memory.vector_store import VectorStore
        vs = VectorStore(persona)
        vs.delete(key)
    except Exception:
        pass
    return {"key": key, "success": True}


@router.post("/search")
async def search_memories(request: Request, body: MemorySearchRequest):
    """クエリで記憶を検索する。"""
    db = _get_db(request)
    persona = get_persona(request)
    try:
        from nous_mcp.tools.memory_tools import _search
        results = _search(db, body.query, body.mode, body.limit, persona)
        if body.min_importance is not None:
            results = [e for e in results if e.importance >= body.min_importance]
        if body.tags:
            results = [e for e in results if any(t in e.tags for t in body.tags)]
        return {
            "results": [_entry_to_dict(e) for e in results],
            "count": len(results),
            "query": body.query,
            "mode": body.mode,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
