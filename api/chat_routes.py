"""
Nous チャット UI WebSocket + REST API ルーター。
Web UI からリアルタイム会話ができるエンドポイントを提供する。
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from config import load_config
from nous_mcp.server import get_persona

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

# テンプレートは main.py で設定する
_templates: Optional[Jinja2Templates] = None
_agent_loops: Dict[str, Any] = {}


def set_templates(templates: Jinja2Templates) -> None:
    global _templates
    _templates = templates


def register_agent_loops(loops: Dict[str, Any]) -> None:
    _agent_loops.update(loops)


# ── ページルート ─────────────────────────────────────────────────────────────


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, persona: Optional[str] = None):
    """チャット UI ページを返す。"""
    if _templates is None:
        return HTMLResponse("<h1>Templates not configured</h1>", status_code=500)
    cfg = load_config()
    active_personas = cfg.get("active_personas", ["herta"])
    resolved_persona = persona or get_persona(request)
    return _templates.TemplateResponse("chat.html", {
        "request": request,
        "persona": resolved_persona,
        "personas": active_personas,
    })


# ── REST API ─────────────────────────────────────────────────────────────────


@router.get("/api/chat/history/{persona}")
async def get_chat_history(persona: str, request: Request, limit: int = 20):
    """現在のアクティブスレッドの会話履歴を取得する。"""
    from nous_mcp.server import get_conversation_db_path
    from memory.conversation_db import ConversationDB
    from config import load_config
    cfg = load_config()
    db = ConversationDB(get_conversation_db_path(persona))
    max_silence = cfg.get("conversation", {}).get("max_silence_hours", 8.0)
    thread = db.get_or_create_active_thread(persona, max_silence_hours=max_silence)
    turns = db.get_recent_turns(thread.id, limit=limit)
    return {
        "thread_id": thread.id,
        "turns": [
            {
                "id": t.id,
                "source": t.source,
                "role": t.role,
                "content": t.content,
                "created_at": t.created_at,
            }
            for t in turns
        ],
    }


@router.post("/api/chat/new_thread")
async def new_chat_thread(request: Request, persona: Optional[str] = None):
    """新しい会話スレッドを強制開始する。"""
    from nous_mcp.server import get_conversation_db_path
    from memory.conversation_db import ConversationDB
    resolved_persona = persona or get_persona(request)
    db = ConversationDB(get_conversation_db_path(resolved_persona))
    thread = db._create_thread(resolved_persona)
    return {"thread_id": thread.id, "created_at": thread.created_at}


@router.get("/api/chat/threads/{persona}")
async def list_chat_threads(persona: str, limit: int = 20):
    """スレッド一覧を取得する。"""
    from nous_mcp.server import get_conversation_db_path
    from memory.conversation_db import ConversationDB
    db = ConversationDB(get_conversation_db_path(persona))
    threads = db.list_threads(persona)
    return {
        "threads": [
            {
                "id": t.id,
                "status": t.status,
                "turn_count": t.turn_count,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in threads[:limit]
        ]
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────


@router.websocket("/ws/chat/{persona}")
async def chat_websocket(websocket: WebSocket, persona: str):
    """チャット UI 用 WebSocket エンドポイント。"""
    await websocket.accept()
    logger.info(f"Chat WS connected for persona: {persona}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            if msg.get("type") != "message":
                continue

            content = msg.get("content", "").strip()
            user_id = msg.get("user_id", "web_user")

            if not content:
                continue

            # タイピングインジケーター
            await websocket.send_text(json.dumps({"type": "typing"}))

            # AgentLoop に処理を委譲（会話 DB 保存も loop が行う）
            loop = _agent_loops.get(persona)
            if loop is not None:
                try:
                    response = await loop.handle_web_message(content, user_id)
                except Exception as e:
                    logger.error(f"AgentLoop error: {e}", exc_info=True)
                    response = f"（処理エラー: {e}）"
            else:
                # AgentLoop が未起動の場合はフォールバック
                response = f"[{persona}] {content} — AgentLoop は未初期化だよ"

            # 感情状態を取得
            emotion = "neutral"
            em_state = None
            try:
                from nous_mcp.server import get_psychology_db_path
                from psychology.emotional_model import EmotionalModel
                em = EmotionalModel(persona, get_psychology_db_path(persona))
                emotion = em.get_display_emotion()
                em_state = em.state
            except Exception:
                pass

            # 応答送信
            await websocket.send_text(json.dumps({
                "type": "message",
                "content": response,
                "emotion": emotion,
            }, ensure_ascii=False))

            # アバター更新（チャット WS 経由）
            try:
                if em_state is not None:
                    await websocket.send_text(json.dumps({
                        "type": "avatar_update",
                        "params": {
                            "emotion": em_state.surface_emotion,
                            "intensity": em_state.surface_intensity,
                            "mood": em_state.mood,
                            "mood_valence": em_state.mood_valence,
                            "mood_arousal": em_state.mood_arousal,
                        },
                    }, ensure_ascii=False))

                    # VRM WebSocket クライアントにもブロードキャスト
                    from api.avatar_routes import broadcast_vrm_state
                    from output.avatar.vrm_web import emotion_to_vrm_expression
                    vrm_name, _ = emotion_to_vrm_expression(em_state.surface_emotion)
                    await broadcast_vrm_state(persona, {
                        "emotion": vrm_name,
                        # 表情変化が見えるよう intensity の最低値を 0.5 に保証する
                        "intensity": max(em_state.surface_intensity, 0.5),
                        "source_emotion": em_state.surface_emotion,
                    })

                # ドライブ更新
                from nous_mcp.server import get_psychology_db_path
                from psychology.drive_system import DriveSystem
                ds = DriveSystem(persona, get_psychology_db_path(persona))
                drives = ds.state
                await websocket.send_text(json.dumps({
                    "type": "drive_update",
                    "drives": {
                        "curiosity": drives.curiosity,
                        "boredom": drives.boredom,
                        "connection": drives.connection,
                        "expression": drives.expression,
                        "mastery": drives.mastery,
                    },
                }, ensure_ascii=False))
            except Exception as e:
                logger.debug(f"Avatar update failed: {e}")

    except WebSocketDisconnect:
        logger.info(f"Chat WS disconnected for persona: {persona}")
    except Exception as e:
        logger.error(f"Chat WS error: {e}", exc_info=True)
