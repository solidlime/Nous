from __future__ import annotations

from nous.application.event_bus import SESSION_ROLLBACK
from nous.infrastructure.logging.structured import get_logger

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
