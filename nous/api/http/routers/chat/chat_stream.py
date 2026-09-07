from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, StreamingResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.config.settings import get_settings
from nous.domain.chat_config import ChatConfigFileRepository
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


# ── shared helper ──────────────────────────────────────────────────


def _resolve_request(request: Request):
    """Return (persona, ctx) or (persona, None)."""
    persona = _resolve_persona_from_request(request)
    ctx = _safe_get_context(persona)
    return persona, ctx


# ── extracted inner helpers (were nested inside chat_endpoint) ─────


async def _do_get_chat_session(persona: str, ctx, session_id: str, limit: int | None = None, offset: int = 0) -> dict:
    """Return session messages dict with tail-based pagination.

    limit/offset は末尾（最新）基準。limit=None なら全件。total は常に全件数。
    """
    from nous.application.chat.session_store import SessionManager

    db = ctx.connection.get_memory_db()
    all_messages = SessionManager.get_messages(db, persona, session_id)
    total = len(all_messages)
    if limit is None:
        return {"session_id": session_id, "messages": all_messages, "total": total}
    end = total - offset
    start = max(0, end - limit)
    return {"session_id": session_id, "messages": all_messages[start:end], "total": total}


async def _do_delete_chat_session(persona: str, ctx, session_id: str) -> dict:
    """Delete session and return confirmation."""
    from nous.application.chat.service import _session_manager
    from nous.application.chat.session_store import SessionManager

    db = ctx.connection.get_memory_db()
    SessionManager.delete_session(db, persona, session_id)
    db.execute("DELETE FROM session_events WHERE persona=? AND session_id=?", (persona, session_id))
    db.commit()
    _session_manager.clear(persona, session_id)
    return {"deleted": True, "session_id": session_id}


# ── HTTP adapter layer ─────────────────────────────────────────────


async def chat_endpoint(request: Request) -> JSONResponse:
    """POST /api/chat/{persona} — register a chat turn (E3 チャット分離)。

    ターンはサーバー内タスクで完遂し、イベントは GET /{persona}/events の SSE ハブから配信。
    202 {"turn_id"} / 実行中 409 / persona 不在 404。
    """
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"detail": "Persona not found"}, status_code=404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("chat_endpoint: invalid JSON body")
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)

    user_message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "main").strip()
    debug_mode = bool(body.get("debug", False))
    _images_raw = body.get("images") or []
    images: list[dict] = _images_raw if isinstance(_images_raw, list) else []

    if not user_message:
        return JSONResponse({"detail": "message is required"}, status_code=400)

    try:
        from nous.api.http.routers.tts import kickoff_caption_task

        kickoff_caption_task(persona, ctx, user_message)
    except Exception:
        logger.exception("chat_endpoint: caption kickoff failed")

    from nous.application.chat.service import ChatService, TurnBusyError

    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)
    if ctx.search_engine is not None:
        ctx.search_engine.set_persona(persona)
    service = ChatService()
    try:
        turn_id = await service.chat_turn(ctx, config, user_message, session_id, debug=debug_mode, images=images)
    except TurnBusyError:
        return JSONResponse({"detail": "turn already running"}, status_code=409)
    return JSONResponse({"turn_id": turn_id}, status_code=202)


async def chat_event_stream(request: Request, persona: str, last_seq: int = 0):
    """SSE generator: snapshot_after リプレイ（id: <seq> 付き）→ ライブ push → keepalive 15s。"""
    from nous.application.chat.service import get_turn_hub

    hub = get_turn_hub()
    queue = hub.subscribe(persona)
    try:
        last = last_seq
        for seq, sse in hub.snapshot_after(persona, last_seq):
            last = seq
            yield f"id: {seq}\n{sse}"
        while True:
            if await request.is_disconnected():
                break
            try:
                seq, sse = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                # Keepalive comment (SSE spec: lines starting with : are comments)
                yield ": keepalive\n\n"
                continue
            if seq <= last:
                continue  # リプレイ済み（subscribe と snapshot の競合分）
            last = seq
            yield f"id: {seq}\n{sse}"
    except asyncio.CancelledError:
        raise  # finally の unsubscribe のみ行い、キャンセルは外へ伝播させる
    except Exception as e:
        logger.debug("chat SSE stream error for persona '%s': %s", persona, e)
    finally:
        hub.unsubscribe(persona, queue)


async def chat_events(request: Request) -> StreamingResponse:
    """GET /api/chat/{persona}/events?last_seq=N — SSE hub stream for chat turns."""
    persona, ctx = _resolve_request(request)
    if not ctx:

        async def not_found():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Persona not found'})}\n\n"

        return StreamingResponse(not_found(), media_type="text/event-stream")

    try:
        last_seq = int(request.query_params.get("last_seq") or 0)
    except ValueError:
        last_seq = 0

    return StreamingResponse(
        chat_event_stream(request, persona, last_seq),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
