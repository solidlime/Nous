"""
Nous ダッシュボード REST API + HTML ルーター。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from nous_mcp.server import get_persona

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_templates: Optional[Jinja2Templates] = None


def set_templates(templates: Jinja2Templates) -> None:
    global _templates
    _templates = templates


# ── ページルート ─────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """ダッシュボード UI ページを返す。"""
    if _templates is None:
        return HTMLResponse("<h1>Templates not configured</h1>", status_code=500)
    from config import load_config
    cfg = load_config()
    persona = get_persona(request)
    active_personas = cfg.get("active_personas", ["herta"])
    return _templates.TemplateResponse("dashboard.html", {
        "request": request,
        "persona": persona,
        "personas": active_personas,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """設定 UI ページを返す。"""
    if _templates is None:
        return HTMLResponse("<h1>Templates not configured</h1>", status_code=500)
    from config import load_config
    cfg = load_config()
    persona = get_persona(request)
    active_personas = cfg.get("active_personas", ["herta"])
    return _templates.TemplateResponse("settings.html", {
        "request": request,
        "persona": persona,
        "personas": active_personas,
    })


# ── REST API ─────────────────────────────────────────────────────────────────


@router.get("/api/dashboard/stats")
async def get_dashboard_stats(request: Request):
    """ダッシュボード統計情報を返す。"""
    persona = get_persona(request)
    result = {"persona": persona}

    # 記憶統計
    try:
        from nous_mcp.server import get_db_path
        from memory.db import MemoryDB
        db = MemoryDB(get_db_path(persona))
        stats = db.get_stats()
        result["memory"] = stats
    except Exception as e:
        result["memory"] = {"error": str(e)}

    # 心理状態
    try:
        from nous_mcp.server import get_psychology_db_path
        from psychology.emotional_model import EmotionalModel
        from psychology.drive_system import DriveSystem
        em = EmotionalModel(persona, get_psychology_db_path(persona))
        ds = DriveSystem(persona, get_psychology_db_path(persona))
        result["psychology"] = {
            "emotion": em.get_display_emotion(),
            "surface_emotion": em.state.surface_emotion,
            "mood": em.state.mood,
            "drives": {
                "curiosity": ds.state.curiosity,
                "boredom": ds.state.boredom,
                "connection": ds.state.connection,
                "expression": ds.state.expression,
                "mastery": ds.state.mastery,
            },
        }
    except Exception as e:
        result["psychology"] = {"error": str(e)}

    # 会話統計
    try:
        from nous_mcp.server import get_conversation_db_path
        from memory.conversation_db import ConversationDB
        from config import load_config
        cfg = load_config()
        conv_db = ConversationDB(get_conversation_db_path(persona))
        max_silence = cfg.get("conversation", {}).get("max_silence_hours", 8.0)
        thread = conv_db.get_or_create_active_thread(persona, max_silence_hours=max_silence)
        result["conversation"] = {
            "active_thread_id": thread.id,
            "active_thread_turns": thread.turn_count,
        }
    except Exception as e:
        result["conversation"] = {"error": str(e)}

    # エージェント状態
    try:
        from nous_mcp.tools.agent_tools import _agent_loops
        loop = _agent_loops.get(persona)
        if loop is not None:
            result["agent"] = await loop.get_status()
        else:
            result["agent"] = {"status": "not_running"}
    except Exception as e:
        result["agent"] = {"status": "error", "error": str(e)}

    return result


@router.get("/api/dashboard/all_stats")
async def get_all_dashboard_stats(request: Request):
    """全アクティブペルソナのダッシュボード統計情報を返す。"""
    from config import load_config
    cfg = load_config()
    active_personas = cfg.get("active_personas", ["herta"])
    results = {}
    for persona in active_personas:
        result = {"persona": persona}
        # 記憶統計
        try:
            from nous_mcp.server import get_db_path
            from memory.db import MemoryDB
            db = MemoryDB(get_db_path(persona))
            result["memory"] = db.get_stats()
        except Exception as e:
            result["memory"] = {"error": str(e)}
        # 心理状態
        try:
            from nous_mcp.server import get_psychology_db_path
            from psychology.emotional_model import EmotionalModel
            from psychology.drive_system import DriveSystem
            em = EmotionalModel(persona, get_psychology_db_path(persona))
            ds = DriveSystem(persona, get_psychology_db_path(persona))
            result["psychology"] = {
                "emotion": em.get_display_emotion(),
                "surface_emotion": em.state.surface_emotion,
                "mood": em.state.mood,
                "drives": {
                    "curiosity": ds.state.curiosity,
                    "boredom": ds.state.boredom,
                    "connection": ds.state.connection,
                    "expression": ds.state.expression,
                    "mastery": ds.state.mastery,
                },
            }
        except Exception as e:
            result["psychology"] = {"error": str(e)}
        # 会話統計
        try:
            from nous_mcp.server import get_conversation_db_path
            from memory.conversation_db import ConversationDB
            conv_db = ConversationDB(get_conversation_db_path(persona))
            max_silence = cfg.get("conversation", {}).get("max_silence_hours", 8.0)
            thread = conv_db.get_or_create_active_thread(persona, max_silence_hours=max_silence)
            result["conversation"] = {
                "active_thread_id": thread.id,
                "active_thread_turns": thread.turn_count,
            }
        except Exception as e:
            result["conversation"] = {"error": str(e)}
        # エージェント状態
        try:
            from nous_mcp.tools.agent_tools import _agent_loops
            loop = _agent_loops.get(persona)
            if loop is not None:
                result["agent"] = await loop.get_status()
            else:
                result["agent"] = {"status": "not_running"}
        except Exception as e:
            result["agent"] = {"status": "error", "error": str(e)}
        results[persona] = result
    return {"personas": results}


@router.get("/api/dashboard/recent_memories")
async def get_recent_memories(request: Request, limit: int = 10):
    """直近の記憶一覧を返す。"""
    persona = get_persona(request)
    from nous_mcp.server import get_db_path
    from memory.db import MemoryDB
    db = MemoryDB(get_db_path(persona))
    memories = db.get_recent(limit=limit)
    return {
        "memories": [
            {
                "key": m.key,
                "content": m.content[:200],
                "importance": m.importance,
                "tags": m.tags,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "elevated": m.elevated,
                "elevation_emotion": m.elevation_emotion,
            }
            for m in memories
        ]
    }


@router.get("/health")
async def health():
    """ヘルスチェックエンドポイント。"""
    from config import load_config
    cfg = load_config()
    return {
        "status": "ok",
        "service": "nous",
        "version": "1.0.0",
        "active_personas": cfg.get("active_personas", ["herta"]),
    }
