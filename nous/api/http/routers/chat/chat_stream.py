from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import StreamingResponse

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


async def _not_found():
    yield f"data: {json.dumps({'type': 'error', 'message': 'Persona not found'})}\n\n"


async def _bad_request():
    yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid JSON'})}\n\n"


async def _empty():
    yield f"data: {json.dumps({'type': 'error', 'message': 'message is required'})}\n\n"


# ── pure logic layer (_do_*) ───────────────────────────────────────


async def _do_chat(
    persona: str,
    ctx,
    user_message: str,
    session_id: str,
    debug: bool = False,
    images: list[dict] | None = None,
):
    """Async generator yielding SSE chunks for chat response."""
    from nous.application.chat_service import ChatService

    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)
    service = ChatService()
    ctx.search_engine.set_persona(persona)

    async for chunk in service.chat(ctx, config, session_id, user_message, debug=debug, images=images or []):
        yield chunk


async def _do_get_chat_session(persona: str, ctx, session_id: str) -> dict:
    """Return session messages dict."""
    from nous.application.chat.session_store import SessionManager

    db = ctx.connection.get_memory_db()
    messages = SessionManager.get_messages(db, persona, session_id)
    return {"session_id": session_id, "messages": messages}


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


async def chat_endpoint(request: Request) -> StreamingResponse:
    """POST /api/chat/{persona} — streaming chat completion."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return StreamingResponse(_not_found(), media_type="text/event-stream")

    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("chat_endpoint: invalid JSON body")
        return StreamingResponse(_bad_request(), media_type="text/event-stream")

    user_message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "main").strip()
    debug_mode = bool(body.get("debug", False))
    images: list[dict] = body.get("images") or []

    if not user_message:
        return StreamingResponse(_empty(), media_type="text/event-stream")

    return StreamingResponse(
        _do_chat(persona, ctx, user_message, session_id, debug_mode, images),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
