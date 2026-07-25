from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response, StreamingResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.application.event_bus import SESSION_ROLLBACK
from nous.config.settings import get_settings
from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_request(request: Request):
    """Return (persona, ctx) or (persona, None)."""
    persona = _resolve_persona_from_request(request)
    ctx = _safe_get_context(persona)
    return persona, ctx


# ── pure logic layer (_do_*) — Request非依存、単体テスト可能 ───────────────


async def _do_get_chat_config(persona: str, ctx) -> dict:
    """Return chat config safe dict for persona."""
    repo = ChatConfigFileRepository(get_settings().data_root)
    try:
        config = repo.get(persona)
    except Exception:  # 設定読み込み失敗時のフォールバック
        logger.warning("get_chat_config: repo.get(%r) failed, returning defaults", persona)
        config = ChatConfig(persona=persona)
    return config.to_safe_dict()


async def _do_save_chat_config(persona: str, ctx, body: dict) -> dict:
    """Save and return updated chat config safe dict."""
    repo = ChatConfigFileRepository(get_settings().data_root)
    current = repo.get(persona)

    update_data = current.model_dump()
    for field_name in ChatConfig.model_fields:
        if field_name in ("persona", "updated_at", "api_key"):
            continue
        if field_name in body:
            update_data[field_name] = body[field_name]
    if "api_key" in body and body["api_key"] and not str(body["api_key"]).endswith("****"):
        update_data["api_key"] = body["api_key"]

    new_config = ChatConfig(**update_data)
    repo.save(new_config)
    return new_config.to_safe_dict()


async def _do_list_mcp_tools(persona: str, ctx) -> dict:
    """Return MCP tools and errors."""
    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)

    if not config.mcp_servers:
        return {"tools": [], "errors": []}

    from nous.infrastructure.mcp_client.pool import MCPClientPool

    tools_out: list[dict] = []
    errors_out: list[str] = []
    try:
        async with MCPClientPool(config.mcp_servers) as pool:
            for tool in pool.list_all_tools():
                desc = tool.description or ""
                server_name = ""
                if desc.startswith("[") and "]" in desc:
                    server_name = desc[1 : desc.index("]")]
                    desc = desc[desc.index("]") + 1 :].strip()
                tools_out.append(
                    {
                        "name": tool.name,
                        "description": desc,
                        "server": server_name,
                    }
                )
    except Exception as e:  # MCPプール接続失敗は非致命的
        logger.warning("get_chat_tools: tool retrieval failed: %s", e)
        errors_out.append(str(e))

    return {"tools": tools_out, "errors": errors_out}


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


async def _do_get_commitments(persona: str, ctx) -> dict:
    """Return active goals and latest reflection insights."""
    goals: list[dict] = []
    insights: list[str] = []

    try:
        goal_result = ctx.memory_service.get_by_tags(["goal", "active"])
        if goal_result.is_ok and goal_result.value:
            goals = [{"content": m.content, "key": m.key} for m in goal_result.value]
    except Exception as e:  # 目標/洞察の取得失敗は非致命的
        logger.warning("get_chat_commitments: goals failed: %s", e)

    try:
        reflection_result = ctx.memory_service.get_by_tags(["reflection"])
        if reflection_result.is_ok and reflection_result.value:
            sorted_refs = sorted(
                reflection_result.value,
                key=lambda m: getattr(m, "created_at", None) or "",
                reverse=True,
            )
            insights = [m.content for m in sorted_refs[:5]]
    except Exception as e:  # 目標/洞察の取得失敗は非致命的
        logger.warning("get_chat_commitments: insights failed: %s", e)

    return {"goals": goals, "insights": insights}


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


async def _do_attachment_upload(persona: str, ctx, filename: str, file_bytes: bytes) -> dict:
    """Save uploaded file to host FS and return metadata dict."""
    import mimetypes
    import os
    from pathlib import Path

    settings = get_settings()
    uploads_dir = Path(settings.data_root) / "uploads" / persona
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name:
        safe_name = "upload"

    dest = uploads_dir / safe_name
    counter = 0
    stem = dest.stem
    suffix = dest.suffix
    while dest.exists():
        counter += 1
        dest = uploads_dir / f"{stem}_{counter}{suffix}"
    safe_name = dest.name

    dest.write_bytes(file_bytes)

    mime_type, _ = mimetypes.guess_type(safe_name)
    mime_type = mime_type or "application/octet-stream"
    size = dest.stat().st_size

    return {
        "filename": safe_name,
        "url": f"/api/chat/{persona}/attachment/{safe_name}",
        "workspace_path": f"/uploads/{persona}/{safe_name}",
        "mime_type": mime_type,
        "size": size,
    }


async def _do_attachment_serve(persona: str, ctx, filename: str) -> dict | None:
    """Resolve file path and mime type for an uploaded attachment. Returns None if not found."""
    import mimetypes
    from pathlib import Path

    settings = get_settings()
    file_path = Path(settings.data_root) / "uploads" / persona / filename
    if not file_path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"
    return {"file_path": str(file_path), "mime_type": mime_type}


async def _do_memory_image_serve(persona: str, ctx, filename: str) -> dict | None:
    """Resolve file path and mime type for a memory image. Returns None if not found."""
    import mimetypes
    from pathlib import Path

    settings = get_settings()
    file_path = Path(settings.data_root) / "persona" / persona / "images" / filename
    if not file_path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "image/png"
    return {"file_path": str(file_path), "mime_type": mime_type}


async def _do_execute_chat_tool(persona: str, ctx, body: dict) -> dict:
    """Execute a builtin memory tool and return result dict."""
    from nous.application.chat.tools.builtin import execute_tool

    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)
    ctx.search_engine.set_persona(persona)

    tool_name = body.get("tool", "")
    tool_input = body.get("input", {})

    result = await execute_tool(ctx, config, tool_name, tool_input)
    if isinstance(result, dict) and "status" in result:
        return result
    return {
        "status": "ok" if result else "error",
        "key": result.get("memory_key", "") if isinstance(result, dict) else "",
        "message": str(result) if not isinstance(result, dict) else result.get("response", ""),
    }


# ── HTTP adapter layer — 元の関数名を維持 ────────────────────────────


async def get_chat_config(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/config — return chat configuration."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(await _do_get_chat_config(persona, ctx))


async def save_chat_config(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/config — update chat configuration."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("save_chat_config: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    try:
        result = await _do_save_chat_config(persona, ctx, body)
    except Exception:  # 最終防衛線: Pydantic/domain validation
        logger.exception("save_chat_config: config validation failed")
        return JSONResponse({"error": "Invalid config"}, status_code=400)
    return JSONResponse(result)


async def list_mcp_tools(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/mcp-tools — return MCP tools list."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(await _do_list_mcp_tools(persona, ctx))


async def chat_endpoint(request: Request) -> StreamingResponse:
    """POST /api/chat/{persona} — streaming chat completion."""
    persona, ctx = _resolve_request(request)
    if not ctx:

        async def not_found():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Persona not found'})}\n\n"

        return StreamingResponse(not_found(), media_type="text/event-stream")

    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("chat_endpoint: invalid JSON body")

        async def bad_request():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Invalid JSON'})}\n\n"

        return StreamingResponse(bad_request(), media_type="text/event-stream")

    user_message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "main").strip()
    debug_mode = bool(body.get("debug", False))
    images: list[dict] = body.get("images") or []

    if not user_message:

        async def empty():
            yield f"data: {json.dumps({'type': 'error', 'message': 'message is required'})}\n\n"

        return StreamingResponse(empty(), media_type="text/event-stream")

    return StreamingResponse(
        _do_chat(persona, ctx, user_message, session_id, debug_mode, images),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def get_chat_commitments(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/commitments — return active goals and insights."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(await _do_get_commitments(persona, ctx))


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


async def attachment_upload(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/attachment/upload — upload file attachment."""
    from starlette.datastructures import UploadFile  # noqa: TC002

    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload:
        return JSONResponse({"error": "file field required"}, status_code=400)

    filename = upload.filename or "upload"
    file_bytes = await upload.read()
    return JSONResponse(await _do_attachment_upload(persona, ctx, filename, file_bytes))


async def attachment_serve(request: Request) -> Response:
    """GET /api/chat/{persona}/attachment/{filename} — serve uploaded file."""
    import os

    from starlette.responses import FileResponse

    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    filename = request.path_params.get("filename", "")
    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    result = await _do_attachment_serve(persona, ctx, safe_name)
    if result is None:
        return JSONResponse({"error": "File not found"}, status_code=404)

    return FileResponse(result["file_path"], media_type=result["mime_type"])


async def memory_image_serve(request: Request) -> Response:
    """GET /api/chat/{persona}/persona/images/{filename} — serve generated image."""
    import os

    from starlette.responses import FileResponse

    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    filename = request.path_params.get("filename", "")
    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name or not safe_name.lower().endswith(".png"):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    result = await _do_memory_image_serve(persona, ctx, safe_name)
    if result is None:
        return JSONResponse({"error": "File not found"}, status_code=404)

    return FileResponse(result["file_path"], media_type=result["mime_type"])


async def execute_chat_tool(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/tool — execute a builtin memory tool."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    body = await request.json()
    tool_name = body.get("tool", "")
    if not tool_name:
        return JSONResponse({"status": "error", "message": "tool name required"}, status_code=400)

    try:
        result = await _do_execute_chat_tool(persona, ctx, body)
        return JSONResponse(result)
    except Exception:  # 最終防衛線
        logger.exception("execute_chat_tool: tool execution failed")
        return JSONResponse({"status": "error", "message": "Tool execution failed"}, status_code=500)


# ── route registration (薄い登録層) ─────────────────────────────────


def register_chat_routes(mcp) -> None:
    """HTTP chat routes — thin registration layer."""
    mcp.custom_route("/api/chat/{persona}/config", methods=["GET"])(get_chat_config)
    mcp.custom_route("/api/chat/{persona}/config", methods=["POST"])(save_chat_config)
    mcp.custom_route("/api/chat/{persona}/mcp-tools", methods=["GET"])(list_mcp_tools)
    mcp.custom_route("/api/chat/{persona}", methods=["POST"])(chat_endpoint)
    mcp.custom_route("/api/chat/{persona}/commitments", methods=["GET"])(get_chat_commitments)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["GET"])(get_chat_session)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["DELETE"])(delete_chat_session)
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/messages/{msg_id}", methods=["PUT"])(
        update_chat_message
    )
    mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/rollback", methods=["POST"])(rollback_chat_session)
    mcp.custom_route("/api/chat/{persona}/attachment/upload", methods=["POST"])(attachment_upload)
    mcp.custom_route("/api/chat/{persona}/attachment/{filename}", methods=["GET"])(attachment_serve)
    mcp.custom_route("/api/chat/{persona}/persona/images/{filename}", methods=["GET"])(memory_image_serve)
    mcp.custom_route("/api/chat/{persona}/tool", methods=["POST"])(execute_chat_tool)
