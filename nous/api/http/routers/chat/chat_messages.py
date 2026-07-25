from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.routers.chat.chat_stream import (
    _do_delete_chat_session,
    _do_get_chat_session,
    _resolve_request,
)
from nous.application.event_bus import SESSION_ROLLBACK
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


# ── pure logic layer (_do_*) ───────────────────────────────────────


def _exclusive_rollback(window, from_id: str):
    """Apply exclusive rollback logic — remove target node and its ancestors.

    Returns result dict from rollback_to or a success dict for root-node case,
    or an error dict when node is not found.
    """
    node = window._nodes.get(from_id)
    if node is None:
        return {"error": f"Message ID {from_id} not found"}
    parent_id = node.get("parent_id")
    if parent_id:
        target_id = parent_id
        if node.get("role") == "assistant":
            parent_node = window._nodes.get(parent_id)
            if parent_node and parent_node.get("role") == "user":
                gp_id = parent_node.get("parent_id")
                if gp_id:
                    target_id = gp_id
        result = window.rollback_to(target_id)
    else:
        old = window._active_leaf_id
        window._active_leaf_id = None
        window._version += 1
        window._persist()
        result = {"old_active_leaf_id": old, "new_active_leaf_id": None}
    return result


async def _do_update_chat_message(persona: str, ctx, session_id: str, msg_id: str, body: dict) -> dict:
    """Update message content with optimistic locking. Returns success dict or error dict."""
    from nous.application.chat.service import _session_manager
    from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA, TreeSessionWindow

    new_content = body.get("content", "").strip()
    expected_version = body.get("expected_version")

    key = (persona, session_id)
    window = _session_manager._sessions.get(key)

    if window:
        if expected_version is not None and window.get_version() != expected_version:
            return {"error": "conflict", "current_version": window.get_version()}
        updated = window.edit_message(msg_id, new_content)
        current_version = window.get_version()
    else:
        db = ctx.connection.get_memory_db()
        db.execute(_CHAT_SESSIONS_SCHEMA)
        db.commit()
        window = TreeSessionWindow.from_db(db, persona, session_id)
        if window is None:
            return {"error": "Session not found"}
        if expected_version is not None and window.get_version() != expected_version:
            return {"error": "conflict", "current_version": window.get_version()}
        updated = window.edit_message(msg_id, new_content)
        current_version = window.get_version()

    if updated is None:
        return {"error": f"Message ID {msg_id} not found"}

    return {"status": "ok", "updated_message": updated, "version": current_version}


async def _do_rollback_chat_session(persona: str, ctx, session_id: str, body: dict) -> dict:
    """Rollback session to given message ID. Returns result dict with remaining messages."""
    from nous.application.chat.service import _session_manager
    from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA, SessionManager, TreeSessionWindow

    from_id = str(body.get("from_id", "")).strip()
    expected_version = body.get("expected_version")
    exclusive = body.get("exclusive", False)

    key = (persona, session_id)
    window = _session_manager._sessions.get(key)

    if window:
        if expected_version is not None and window.get_version() != expected_version:
            return {"error": "conflict", "current_version": window.get_version()}
        old_path = window.get_active_path()
        if exclusive:
            result = _exclusive_rollback(window, from_id)
            if isinstance(result, dict) and "error" in result:
                return result
        else:
            result = window.rollback_to(from_id)
        current_version = window.get_version()
    else:
        db = ctx.connection.get_memory_db()
        db.execute(_CHAT_SESSIONS_SCHEMA)
        db.commit()
        window = TreeSessionWindow.from_db(db, persona, session_id)
        if window is None:
            return {"error": "Session not found"}
        if expected_version is not None and window.get_version() != expected_version:
            return {"error": "conflict", "current_version": window.get_version()}
        old_path = window.get_active_path()
        if exclusive:
            result = _exclusive_rollback(window, from_id)
            if isinstance(result, dict) and "error" in result:
                return result
        else:
            result = window.rollback_to(from_id)
        current_version = window.get_version()
        _session_manager._sessions[key] = window

    if result is None:
        return {"error": f"Message ID {from_id} not found"}

    # Compute removed_user_text: last user message removed from active path
    new_path_ids = {msg["id"] for msg in window.get_active_path()}
    removed_user_text = None
    for msg in reversed(old_path):
        if msg["id"] not in new_path_ids and msg["role"] == "user":
            removed_user_text = msg["content"]
            break

    db = ctx.connection.get_memory_db()
    remaining = SessionManager.get_messages(db, persona, session_id)

    try:
        await ctx.event_bus.publish(
            SESSION_ROLLBACK,
            {"persona": persona, "session_id": session_id, "remaining_count": len(remaining)},
        )
    except Exception:
        logger.exception("rollback_chat_session: SSE publish failed")
        # 公開失敗は非致命的、ロールバックは継続

    return {
        "active_leaf_id": from_id,
        "remaining_messages": remaining,
        "removed_user_text": removed_user_text,
        "version": current_version,
    }


# ── HTTP adapter layer ─────────────────────────────────────────────


async def get_chat_session(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/sessions/{session_id} — return session messages."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    session_id = request.path_params.get("session_id", "")
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    return JSONResponse(await _do_get_chat_session(persona, ctx, session_id))


async def delete_chat_session(request: Request) -> JSONResponse:
    """DELETE /api/chat/{persona}/sessions/{session_id} — delete a session."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    session_id = request.path_params.get("session_id", "")
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    return JSONResponse(await _do_delete_chat_session(persona, ctx, session_id))


async def update_chat_message(request: Request) -> JSONResponse:
    """PUT /api/chat/{persona}/sessions/{session_id}/messages/{msg_id} — update message.

    Request body: {"content": "...", "expected_version": N}
    Response: {"status": "ok", "updated_message": {...}, "version": N+1}
    """
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    session_id = request.path_params.get("session_id", "")
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    msg_id = request.path_params.get("msg_id", "")
    if not msg_id:
        return JSONResponse({"error": "msg_id is required"}, status_code=400)

    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("update_chat_message: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    new_content = body.get("content")
    if not isinstance(new_content, str) or not new_content.strip():
        return JSONResponse({"error": "content must be a non-empty string"}, status_code=400)

    expected_version = body.get("expected_version")
    if expected_version is not None and not isinstance(expected_version, int):
        return JSONResponse({"error": "expected_version must be an integer"}, status_code=400)

    try:
        result = await _do_update_chat_message(persona, ctx, session_id, msg_id, body)
    except Exception as e:  # 最終防衛線
        logger.exception("update_chat_message failed: %s", e)
        return JSONResponse({"error": "Internal server error"}, status_code=500)

    if result.get("error") == "conflict":
        return JSONResponse(result, status_code=409)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)


async def rollback_chat_session(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/sessions/{session_id}/rollback — rollback session.

    Request body: {"from_id": "uuid-string", "expected_version": N, "exclusive": bool}
    """
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    session_id = request.path_params.get("session_id", "")
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("rollback_chat_session: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from_id = str(body.get("from_id", "")).strip()
    if not from_id:
        return JSONResponse({"error": "from_id must be a non-empty string"}, status_code=400)

    expected_version = body.get("expected_version")
    if expected_version is not None and not isinstance(expected_version, int):
        return JSONResponse({"error": "expected_version must be an integer"}, status_code=400)

    try:
        result = await _do_rollback_chat_session(persona, ctx, session_id, body)
    except Exception as e:  # 最終防衛線
        logger.exception("rollback_chat_session failed: %s", e)
        return JSONResponse({"error": "Internal server error"}, status_code=500)

    if result.get("error") == "conflict":
        return JSONResponse(result, status_code=409)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)
