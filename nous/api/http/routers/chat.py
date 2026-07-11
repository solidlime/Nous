from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response, StreamingResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
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
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(ctx.connection.get_memory_db())
        config = repo.get(persona)
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

        from nous.domain.chat_config import ChatConfig, ChatConfigRepository

        repo = ChatConfigRepository(ctx.connection.get_memory_db())
        current = repo.get(persona)

        update_data = current.model_dump()
        for field_name in (
            "provider",
            "model",
            "base_url",
            "system_prompt",
            "temperature",
            "max_tokens",
            "max_window_turns",
            "max_tool_calls",
            "auto_extract",
            "extract_model",
            "extract_max_tokens",
            "tool_result_max_chars",
            "mcp_servers",
            "enabled_skills",
            "reflection_enabled",
            "reflection_threshold",
            "reflection_min_interval_hours",
            "session_summarize",
            "retrieval_recency_weight",
            "retrieval_importance_weight",
            "retrieval_relevance_weight",
            "display_history_turns",
            "housekeeping_threshold",
            "mental_model_enabled",
            "mental_model_min_samples",
            "max_stored_messages",
            "context_max_tokens",
            "context_compression_threshold",
            "context_compression_mode",
            "context_keep_recent_turns",
            "context_compress_system_prompt",
            "context_compress_history",
            "memory_preload_count",
            "enable_parallel_tools",
            "image_gen_enabled",
            "image_gen_provider",
            "image_gen_dalle_model",
            "image_gen_stability_url",
            "enable_memory_tools",
            "debug_mode",
            "dynamic_temperature",
            "emotion_temperature_scale",
            "top_p",
            "context_use_llm_summary",
            "episode_consolidation_enabled",
            "episode_search_enabled",
            "irodori_enabled",
            "portrait_enabled",
            "opensandbox_url",
        ):
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
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(ctx.connection.get_memory_db())
        config = repo.get(persona)
        service = ChatService()

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
        """F2: 会話履歴復元 — セッションのメッセージ一覧を返す。"""
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
        _session_manager.clear(persona, session_id)
        return JSONResponse({"deleted": True, "session_id": session_id})

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/messages/{msg_index}", methods=["PUT"])
    async def update_chat_message(request: Request) -> JSONResponse:
        """メッセージ 1 件の content を直接更新する（undo スタック非破壊）。

        PUT /api/chat/{persona}/sessions/{session_id}/messages/{msg_index}
        Request body: {"content": "新しいテキスト"}
        Response: {"status": "ok", "updated_message": {...}}
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        session_id = request.path_params.get("session_id", "")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        try:
            msg_index_str = request.path_params.get("msg_index", "")
            msg_index = int(msg_index_str)
        except (ValueError, TypeError):
            return JSONResponse({"error": "msg_index must be an integer"}, status_code=400)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        new_content = body.get("content")
        if not isinstance(new_content, str) or not new_content.strip():
            return JSONResponse({"error": "content must be a non-empty string"}, status_code=400)

        try:
            from nous.application.chat.service import _session_manager
            from nous.application.chat.session_store import SessionWindow

            key = (persona, session_id)
            window = _session_manager._sessions.get(key)

            if window:
                updated = window.update_message(msg_index, new_content.strip())
            else:
                db = ctx.connection.get_memory_db()
                from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA

                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
                window = SessionWindow.from_db(db, persona, session_id)
                if window is None:
                    return JSONResponse({"error": "Session not found"}, status_code=404)
                updated = window.update_message(msg_index, new_content.strip())

            if updated is None:
                return JSONResponse(
                    {"error": f"Message index {msg_index} out of range"},
                    status_code=404,
                )
            return JSONResponse({"status": "ok", "updated_message": updated})
        except Exception as e:
            logger.exception("update_chat_message failed: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/chat/{persona}/sessions/{session_id}/rollback", methods=["POST"])
    async def rollback_chat_session(request: Request) -> JSONResponse:
        """ロールバック: keep_until インデックスまでメッセージを保持し、以降を削除。

        Request body: {"keep_until": int}
        - keep_until=2 → インデックス 0,1 を保持、2以降を削除

        Response: {"removed_count": N, "remaining_messages": [...],
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

        keep_until = body.get("keep_until", 0)
        if not isinstance(keep_until, int) or keep_until < 0:
            return JSONResponse({"error": "keep_until must be non-negative integer"}, status_code=400)

        try:
            from nous.application.chat.service import _session_manager
            from nous.application.chat.session_store import SessionManager, SessionWindow

            key = (persona, session_id)
            window = _session_manager._sessions.get(key)

            if window:
                removed = window.truncate_to(keep_until)
            else:
                # Window not in memory — load from DB, truncate, persist
                from nous.application.chat.session_store import _CHAT_SESSIONS_SCHEMA

                db = ctx.connection.get_memory_db()
                db.execute(_CHAT_SESSIONS_SCHEMA)
                db.commit()
                window = SessionWindow.from_db(db, persona, session_id)
                if window is None:
                    return JSONResponse({"error": "Session not found"}, status_code=404)
                removed = window.truncate_to(keep_until)

            db = ctx.connection.get_memory_db()
            remaining = SessionManager.get_messages(db, persona, session_id)

            # Return the user message text that was just removed (if any) for input field population
            removed_user_text = None
            for msg in reversed(removed):
                if msg["role"] == "user":
                    removed_user_text = msg["content"]
                    break

            return JSONResponse(
                {
                    "removed_count": len(removed),
                    "remaining_messages": remaining,
                    "removed_user_text": removed_user_text,
                }
            )
        except Exception as e:
            logger.exception("rollback_chat_session failed: %s", e)
            return JSONResponse({"error": str(e)}, status_code=500)

    @mcp.custom_route("/api/chat/{persona}/housekeeping", methods=["POST"])
    async def run_housekeeping(request: Request) -> JSONResponse:
        """コンテキスト整理: staleなgoals/itemsをLLMで判定・削除する。"""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        from nous.application.chat.memory_llm import run_context_housekeeping
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(ctx.connection.get_memory_db())
        config = repo.get(persona)
        try:
            result = await run_context_housekeeping(ctx, config)
            result.pop("cancelled_promises", None)
            return JSONResponse(result)
        except Exception as e:
            logger.warning("housekeeping failed: %s", e)
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
                "workspace_path": f"/uploads/{safe_name}",
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

    @mcp.custom_route("/api/chat/{persona}/tool", methods=["POST"])
    async def execute_chat_tool(request: Request) -> JSONResponse:
        """Execute a builtin memory tool directly (for slash commands)."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        from nous.application.chat.tools.builtin import execute_tool
        from nous.domain.chat_config import ChatConfigRepository

        repo = ChatConfigRepository(ctx.connection.get_memory_db())
        config = repo.get(persona)
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
