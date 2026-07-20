from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response, StreamingResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.application.event_bus import SESSION_ROLLBACK
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_chat_routes(mcp) -> None:

    @mcp.custom_route("/api/chat/{persona}/config", methods=["GET"])
    async def get_chat_config(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
        from nous.config.settings import get_settings

        repo = ChatConfigFileRepository(get_settings().data_root)
        try:
            config = repo.get(persona)
        except Exception:
            logger.warning("get_chat_config: repo.get(%r) failed, returning defaults", persona)
            config = ChatConfig(persona=persona)
        return JSONResponse(config.to_safe_dict())

    @mcp.custom_route("/api/chat/{persona}/config", methods=["POST"])
    async def save_chat_config(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
        from nous.config.settings import get_settings

        repo = ChatConfigFileRepository(get_settings().data_root)
        current = repo.get(persona)

        update_data = current.model_dump()
        # 動的ホワイトリスト: persona, updated_at, api_key 以外の全フィールド
        for field_name in ChatConfig.model_fields:
            if field_name in ("persona", "updated_at", "api_key"):
                continue
            if field_name in body:
                update_data[field_name] = body[field_name]
        if "api_key" in body and body["api_key"] and not str(body["api_key"]).endswith("****"):
            update_data["api_key"] = body["api_key"]

        try:
            new_config = ChatConfig(**update_data)
        except Exception as e:
            return JSONResponse({"error": f"Invalid config: {e}"}, status_code=400)

        repo.save(new_config)
        return JSONResponse(new_config.to_safe_dict())

    @mcp.custom_route("/api/chat/{persona}/mcp-tools", methods=["GET"])
    async def list_mcp_tools(request: Request) -> JSONResponse:
        """MCP サーバーのツール一覧を返す。"""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        from nous.domain.chat_config import ChatConfigFileRepository
        from nous.config.settings import get_settings

        repo = ChatConfigFileRepository(get_settings().data_root)
        config = repo.get(persona)

        if not config.mcp_servers:
            return JSONResponse({"tools": [], "errors": []})

        from nous.infrastructure.mcp_client.pool import MCPClientPool

        tools_out: list[dict] = []
        errors_out: list[str] = []
        try:
            async with MCPClientPool(config.mcp_servers) as pool:
                for tool in pool.list_all_tools():
                    # description から [server_name] プレフィックスを抽出
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
        except Exception as e:
            errors_out.append(str(e))

        return JSONResponse({"tools": tools_out, "errors": errors_out})

    @mcp.custom_route("/api/chat/{persona}", methods=["POST"])
    async def chat_endpoint(request: Request) -> StreamingResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:

            async def not_found():
                yield f"data: {json.dumps({'type': 'error', 'message': 'Persona not found'})}\n\n"

            return StreamingResponse(not_found(), media_type="text/event-stream")

        try:
            body = await request.json()
        except Exception:

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

        from nous.application.chat_service import ChatService
        from nous.domain.chat_config import ChatConfigFileRepository
        from nous.config.settings import get_settings

        repo = ChatConfigFileRepository(get_settings().data_root)
        config = repo.get(persona)
        service = ChatService()

        # Ensure search engine uses the correct persona for semantic search
        ctx.search_engine.set_persona(persona)

        async def generate():
            async for chunk in service.chat(ctx, config, session_id, user_message, debug=debug_mode, images=images):
                yield chunk

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @mcp.custom_route("/api/chat/{persona}/commitments", methods=["GET"])
    async def get_chat_commitments(request: Request) -> JSONResponse:
        """アクティブなgoals・最新リフレクション洞察を返す。"""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        goals: list[dict] = []
        insights: list[str] = []

        try:
            goal_result = ctx.memory_service.get_by_tags(["goal", "active"])
            if goal_result.is_ok and goal_result.value:
                goals = [{"content": m.content, "key": m.key} for m in goal_result.value]
        except Exception as e:
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
        except Exception as e:
            logger.warning("get_chat_commitments: insights failed: %s", e)

        return JSONResponse({"goals": goals, "insights": insights})

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["GET"])
    async def get_chat_session(request: Request) -> JSONResponse:
        """F2: 会話履歴復元 — セッションのメッセージ一覧を返す。

        Response の各メッセージには `id` (UUID) フィールドが含まれる。
        フロントエンドはこの `id` を使用して編集・ロールバック操作を行う。
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        session_id = request.path_params.get("session_id", "")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        from nous.application.chat.session_store import SessionManager

        db = ctx.connection.get_memory_db()
        messages = SessionManager.get_messages(db, persona, session_id)
        return JSONResponse({"session_id": session_id, "messages": messages})

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}", methods=["DELETE"])
    async def delete_chat_session(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        session_id = request.path_params.get("session_id", "")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        from nous.application.chat.service import _session_manager
        from nous.application.chat.session_store import SessionManager

        db = ctx.connection.get_memory_db()
        SessionManager.delete_session(db, persona, session_id)
        db.execute("DELETE FROM session_events WHERE persona=? AND session_id=?", (persona, session_id))
        db.commit()
        _session_manager.clear(persona, session_id)
        return JSONResponse({"deleted": True, "session_id": session_id})

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/messages/{msg_id}", methods=["PUT"])
    async def update_chat_message(request: Request) -> JSONResponse:
        """メッセージ 1 件の content を直接更新する（undo スタック非破壊）。

        PUT /api/chat/{persona}/sessions/{session_id}/messages/{msg_id}
        Request body: {"content": "新しいテキスト", "expected_version": 3}
        Response: {"status": "ok", "updated_message": {...}, "version": 4}
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
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
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        new_content = body.get("content")
        if not isinstance(new_content, str) or not new_content.strip():
            return JSONResponse({"error": "content must be a non-empty string"}, status_code=400)

        expected_version = body.get("expected_version")
        if expected_version is not None and not isinstance(expected_version, int):
            return JSONResponse({"error": "expected_version must be an integer"}, status_code=400)

        try:
            from nous.application.chat.service import _session_manager
            from nous.application.chat.session_store import TreeSessionWindow

            key = (persona, session_id)
            window = _session_manager._sessions.get(key)

            if window:
                # 楽観的ロックチェック
                if expected_version is not None and window.get_version() != expected_version:
                    return JSONResponse(
                        {
                            "error": "conflict",
                            "current_version": window.get_version(),
                        },
                        status_code=409,
                    )
                updated = window.edit_message(msg_id, new_content.strip())
                current_version = window.get_version()
            else:
                db = ctx.connection.get_memory_db()
                from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA

                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
                window = TreeSessionWindow.from_db(db, persona, session_id)
                if window is None:
                    return JSONResponse({"error": "Session not found"}, status_code=404)
                # DBからロードした場合も expected_version チェック
                if expected_version is not None and window.get_version() != expected_version:
                    return JSONResponse(
                        {
                            "error": "conflict",
                            "current_version": window.get_version(),
                        },
                        status_code=409,
                    )
                updated = window.edit_message(msg_id, new_content.strip())
                current_version = window.get_version()

            if updated is None:
                return JSONResponse(
                    {"error": f"Message ID {msg_id} not found"},
                    status_code=404,
                )
            return JSONResponse({"status": "ok", "updated_message": updated, "version": current_version})
        except Exception as e:
            logger.exception("update_chat_message failed: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/rollback", methods=["POST"])
    async def rollback_chat_session(request: Request) -> JSONResponse:
        """ロールバック: from_id の位置までメッセージを保持し、以降を削除。

        Request body: {"from_id": "uuid-string"}
        - from_id 以降（該当メッセージ含む）のアクティブパスを削除

        Response: {"active_leaf_id": "...", "remaining_messages": [...],
                    "removed_user_text": "..." | null}
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        session_id = request.path_params.get("session_id", "")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        from_id = str(body.get("from_id", "")).strip()
        if not from_id:
            return JSONResponse({"error": "from_id must be a non-empty string"}, status_code=400)

        expected_version = body.get("expected_version")
        if expected_version is not None and not isinstance(expected_version, int):
            return JSONResponse({"error": "expected_version must be an integer"}, status_code=400)

        try:
            from nous.application.chat.service import _session_manager
            from nous.application.chat.session_store import SessionManager, TreeSessionWindow

            key = (persona, session_id)
            window = _session_manager._sessions.get(key)

            if window:
                # 楽観的ロックチェック
                if expected_version is not None and window.get_version() != expected_version:
                    return JSONResponse(
                        {
                            "error": "conflict",
                            "current_version": window.get_version(),
                        },
                        status_code=409,
                    )
                # Capture old active path before rollback for removed_user_text
                old_path = window.get_active_path()
                exclusive = body.get("exclusive", False)
                if exclusive:
                    node = window._nodes.get(from_id)
                    if node is None:
                        return JSONResponse(
                            {"error": f"Message ID {from_id} not found"},
                            status_code=404,
                        )
                    parent_id = node.get("parent_id")
                    if parent_id:
                        result = window.rollback_to(parent_id)
                    else:
                        old = window._active_leaf_id
                        window._active_leaf_id = None
                        window._version += 1
                        window._persist()
                        result = {"old_active_leaf_id": old, "new_active_leaf_id": None}
                else:
                    result = window.rollback_to(from_id)
                current_version = window.get_version()
            else:
                # Window not in memory — load from DB, rollback, persist
                from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA

                db = ctx.connection.get_memory_db()
                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
                window = TreeSessionWindow.from_db(db, persona, session_id)
                if window is None:
                    return JSONResponse({"error": "Session not found"}, status_code=404)
                if expected_version is not None and window.get_version() != expected_version:
                    return JSONResponse(
                        {
                            "error": "conflict",
                            "current_version": window.get_version(),
                        },
                        status_code=409,
                    )
                old_path = window.get_active_path()
                exclusive = body.get("exclusive", False)
                if exclusive:
                    node = window._nodes.get(from_id)
                    if node is None:
                        return JSONResponse(
                            {"error": f"Message ID {from_id} not found"},
                            status_code=404,
                        )
                    parent_id = node.get("parent_id")
                    if parent_id:
                        result = window.rollback_to(parent_id)
                    else:
                        old = window._active_leaf_id
                        window._active_leaf_id = None
                        window._version += 1
                        window._persist()
                        result = {"old_active_leaf_id": old, "new_active_leaf_id": None}
                else:
                    result = window.rollback_to(from_id)
                current_version = window.get_version()
                _session_manager._sessions[key] = window

            if result is None:
                return JSONResponse(
                    {"error": f"Message ID {from_id} not found"},
                    status_code=404,
                )

            # Compute removed_user_text: last user message that was in old path but not in new path
            new_path_ids = {msg["id"] for msg in window.get_active_path()}
            removed_user_text = None
            for msg in reversed(old_path):
                if msg["id"] not in new_path_ids and msg["role"] == "user":
                    removed_user_text = msg["content"]
                    break

            db = ctx.connection.get_memory_db()
            remaining = SessionManager.get_messages(db, persona, session_id)

            # SSEでロールバックを通知
            try:
                await ctx.event_bus.publish(
                    SESSION_ROLLBACK,
                    {"persona": persona, "session_id": session_id, "remaining_count": len(remaining)},
                )
            except Exception:
                pass  # 通知失敗はロールバック自体を失敗させない

            return JSONResponse(
                {
                    "active_leaf_id": from_id,
                    "remaining_messages": remaining,
                    "removed_user_text": removed_user_text,
                    "version": current_version,
                }
            )
        except Exception as e:
            logger.exception("rollback_chat_session failed: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/chat/{persona}/attachment/upload", methods=["POST"])
    async def attachment_upload(request: Request) -> JSONResponse:
        """チャット添付ファイルをホストFSに直接保存する（サンドボックス不要）。"""
        import mimetypes
        import os
        from pathlib import Path

        from starlette.datastructures import UploadFile  # noqa: TC002

        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        from nous.config.settings import get_settings

        settings = get_settings()
        uploads_dir = Path(settings.data_root) / "uploads" / persona
        uploads_dir.mkdir(parents=True, exist_ok=True)

        form = await request.form()
        upload: UploadFile = form.get("file")
        if not upload:
            return JSONResponse({"error": "file field required"}, status_code=400)

        filename = upload.filename or "upload"
        # Sanitize filename
        safe_name = os.path.basename(filename).replace("..", "").strip()
        if not safe_name:
            safe_name = "upload"

        dest = uploads_dir / safe_name
        # Avoid overwrite: append counter if needed
        counter = 0
        stem = dest.stem
        suffix = dest.suffix
        while dest.exists():
            counter += 1
            dest = uploads_dir / f"{stem}_{counter}{suffix}"
        safe_name = dest.name

        dest.write_bytes(await upload.read())

        mime_type, _ = mimetypes.guess_type(safe_name)
        mime_type = mime_type or "application/octet-stream"
        size = dest.stat().st_size

        return JSONResponse(
            {
                "filename": safe_name,
                "url": f"/api/chat/{persona}/attachment/{safe_name}",
                "workspace_path": f"/uploads/{persona}/{safe_name}",
                "mime_type": mime_type,
                "size": size,
            }
        )

    @mcp.custom_route("/api/chat/{persona}/attachment/{filename}", methods=["GET"])
    async def attachment_serve(request: Request) -> Response:
        """アップロード済み添付ファイルをサーブする。"""
        import mimetypes
        import os
        from pathlib import Path

        from starlette.responses import FileResponse

        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        filename = request.path_params.get("filename", "")
        safe_name = os.path.basename(filename).replace("..", "").strip()
        if not safe_name:
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        from nous.config.settings import get_settings

        settings = get_settings()
        file_path = Path(settings.data_root) / "uploads" / persona / safe_name
        if not file_path.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        mime_type, _ = mimetypes.guess_type(safe_name)
        mime_type = mime_type or "application/octet-stream"
        return FileResponse(str(file_path), media_type=mime_type)

    @mcp.custom_route("/api/chat/{persona}/persona/images/{filename}", methods=["GET"])
    async def memory_image_serve(request: Request) -> Response:
        """Serve image generation results from memory storage."""
        import mimetypes
        import os
        from pathlib import Path

        from starlette.responses import FileResponse

        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        filename = request.path_params.get("filename", "")
        safe_name = os.path.basename(filename).replace("..", "").strip()
        if not safe_name or not safe_name.lower().endswith(".png"):
            return JSONResponse({"error": "Invalid filename"}, status_code=400)

        from nous.config.settings import get_settings

        settings = get_settings()
        file_path = Path(settings.data_root) / "persona" / persona / "images" / safe_name
        if not file_path.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        mime_type, _ = mimetypes.guess_type(safe_name)
        mime_type = mime_type or "image/png"
        return FileResponse(str(file_path), media_type=mime_type)

    @mcp.custom_route("/api/chat/{persona}/tool", methods=["POST"])
    async def execute_chat_tool(request: Request) -> JSONResponse:
        """Execute a builtin memory tool directly (for slash commands)."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        from nous.application.chat.tools.builtin import execute_tool
        from nous.domain.chat_config import ChatConfigFileRepository
        from nous.config.settings import get_settings

        repo = ChatConfigFileRepository(get_settings().data_root)
        config = repo.get(persona)

        # Ensure search engine uses the correct persona for semantic search
        ctx.search_engine.set_persona(persona)

        body = await request.json()
        tool_name = body.get("tool", "")
        tool_input = body.get("input", {})
        if not tool_name:
            return JSONResponse({"status": "error", "message": "tool name required"}, status_code=400)
        try:
            result = await execute_tool(ctx, config, tool_name, tool_input)
            # Ensure response has {status: "ok"} | {status: "error", message} format
            if isinstance(result, dict) and "status" in result:
                return JSONResponse(result)
            return JSONResponse(
                {
                    "status": "ok" if result else "error",
                    "key": result.get("memory_key", "") if isinstance(result, dict) else "",
                    "message": str(result) if not isinstance(result, dict) else result.get("response", ""),
                }
            )
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
