from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response

from nous.api.http.deps import _PERSONA_PATTERN
from nous.api.http.routers.chat.chat_stream import _resolve_request
from nous.config.settings import get_settings
from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


# ── pure logic layer (_do_*) ───────────────────────────────────────


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
    for field_name in ChatConfig._all_flat_fields():
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


# ── HTTP adapter layer ─────────────────────────────────────────────


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


async def get_chat_commitments(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/commitments — return active goals and insights."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(
        await _do_get_commitments(persona, ctx), headers={"Content-Type": "application/json; charset=utf-8"}
    )


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
    if not ctx or not _PERSONA_PATTERN.match(persona):
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
    if not ctx or not _PERSONA_PATTERN.match(persona):
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
