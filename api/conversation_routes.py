"""
Nous 会話スレッド閲覧 REST API ルーター。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query

from nous_mcp.server import get_persona, get_conversation_db_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _get_conv_db(request: Request):
    persona = get_persona(request)
    from memory.conversation_db import ConversationDB
    return ConversationDB(get_conversation_db_path(persona)), persona


@router.get("")
async def list_conversations(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """会話スレッド一覧を取得する。"""
    db, persona = _get_conv_db(request)
    threads = db.list_threads(persona, status=status)
    return {
        "threads": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "turn_count": t.turn_count,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "has_summary": bool(t.summary),
            }
            for t in threads[:limit]
        ],
        "total": len(threads),
    }


@router.get("/active")
async def get_active_thread(request: Request):
    """現在のアクティブスレッドを取得する。"""
    db, persona = _get_conv_db(request)
    from config import load_config
    cfg = load_config()
    max_silence = cfg.get("conversation", {}).get("max_silence_hours", 8.0)
    thread = db.get_or_create_active_thread(persona, max_silence_hours=max_silence)
    turns = db.get_recent_turns(thread.id, limit=20)
    return {
        "thread": {
            "id": thread.id,
            "status": thread.status,
            "turn_count": thread.turn_count,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
        },
        "recent_turns": [
            {
                "id": t.id,
                "source": t.source,
                "role": t.role,
                "content": t.content,
                "created_at": t.created_at,
                "user_id": t.user_id,
                "channel_id": t.channel_id,
            }
            for t in turns
        ],
    }


@router.get("/{thread_id}")
async def get_thread(thread_id: str, request: Request, limit: int = Query(50, ge=1, le=200)):
    """スレッドの詳細と会話ターンを取得する。"""
    db, persona = _get_conv_db(request)
    thread = db.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    turns = db.get_recent_turns(thread_id, limit=limit)
    return {
        "thread": {
            "id": thread.id,
            "title": thread.title,
            "status": thread.status,
            "turn_count": thread.turn_count,
            "created_at": thread.created_at,
            "updated_at": thread.updated_at,
            "summary": thread.summary,
        },
        "turns": [
            {
                "id": t.id,
                "source": t.source,
                "role": t.role,
                "content": t.content,
                "created_at": t.created_at,
                "user_id": t.user_id,
                "channel_id": t.channel_id,
                "metadata": t.metadata,
            }
            for t in turns
        ],
    }


@router.post("/new")
async def create_new_thread(request: Request):
    """新しいスレッドを強制的に作成する。"""
    db, persona = _get_conv_db(request)
    from memory.conversation_db import ConversationThread
    import uuid
    from datetime import datetime
    thread = ConversationThread(
        id=str(uuid.uuid4()),
        persona=persona,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )
    # _create_thread を直接呼ぶ
    thread = db._create_thread(persona)
    return {"thread_id": thread.id, "created_at": thread.created_at}
