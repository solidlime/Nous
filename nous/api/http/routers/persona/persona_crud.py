from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _PERSONA_PATTERN, _resolve_persona_from_request, _safe_get_context
from nous.application.use_cases import AppContextRegistry
from nous.config.settings import Settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


async def _do_create_persona(persona_name: str) -> dict:
    """Create a new persona. Returns status dict or error dict."""
    settings = Settings()
    persona_dir = Path(settings.persona_dir) / persona_name
    if persona_dir.exists():
        return {"error": f"Persona '{persona_name}' already exists"}
    # AppContextRegistry.get は既存ペルソナディレクトリを要求するため先に作成する
    persona_dir.mkdir(parents=True)
    ctx = AppContextRegistry.get(persona_name)
    if ctx is None:
        return {"error": "Failed to initialize persona"}
    return {
        "status": "ok",
        "persona": persona_name,
        "message": f"Persona '{persona_name}' created",
    }


async def create_persona(request: Request) -> JSONResponse:
    """POST /api/personas — create a new persona."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("create_persona: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    persona_name = (body.get("name") or "").strip()
    if not persona_name:
        return JSONResponse({"error": "Field 'name' is required"}, status_code=400)
    if not _PERSONA_PATTERN.match(persona_name):
        return JSONResponse(
            {"error": "ペルソナ名には英数字・ハイフン・アンダースコアのみ使用できます"},
            status_code=400,
        )
    result = await _do_create_persona(persona_name)
    if "error" in result:
        status = 409 if "already exists" in result["error"] else 500
        return JSONResponse(result, status_code=status)
    return JSONResponse(result, status_code=201)


async def _do_delete_persona(persona: str) -> dict:
    """Delete a persona by name. Returns status dict or error dict."""
    settings = Settings()
    persona_dir = (Path(settings.persona_dir) / persona).resolve()
    root = Path(settings.persona_dir).resolve()
    # ponytail: strict-subdir check; is_relative_to alone would admit persona_dir == root
    if persona_dir == root or not persona_dir.is_relative_to(root):
        return {"error": "Invalid persona name"}
    if not persona_dir.exists():
        return {"error": f"Persona '{persona}' not found"}
    try:
        if persona in AppContextRegistry._contexts:
            AppContextRegistry._contexts[persona].close()
            del AppContextRegistry._contexts[persona]
        shutil.rmtree(persona_dir)
        return {"status": "ok", "deleted": persona}
    # 最終防衛線: 予期せぬ削除エラー
    except Exception:
        logger.exception("delete_persona failure")
        return {"error": "Internal server error"}


async def delete_persona(request: Request) -> JSONResponse:
    """DELETE /api/personas/{persona} — delete a persona."""
    persona = _resolve_persona_from_request(request)
    result = await _do_delete_persona(persona)
    if "error" in result:
        status_code = 400 if "Invalid" in result["error"] else 404 if "not found" in result["error"] else 500
        return JSONResponse(result, status_code=status_code)
    return JSONResponse(result)


async def _do_update_persona_profile(persona: str, ctx, body: dict) -> dict:
    """Update persona profile fields. Returns status dict or error dict."""
    updated = []
    if "user_info" in body and isinstance(body["user_info"], dict):
        result = ctx.persona_service.update_user_info(persona, body["user_info"])
        if result.is_ok:
            updated.append("user_info")
    if "persona_info" in body and isinstance(body["persona_info"], dict):
        result = ctx.persona_service.update_persona_info(persona, body["persona_info"])
        if result.is_ok:
            updated.append("persona_info")
    if "relationship_status" in body:
        result = ctx.persona_service.update_relationship(persona, body["relationship_status"])
        if result.is_ok:
            updated.append("relationship_status")
    if not updated:
        return {"error": "No valid fields to update"}
    return {"status": "ok", "updated": updated}


async def update_persona_profile(request: Request) -> JSONResponse:
    """PUT /api/personas/{persona}/profile — update persona profile."""
    persona = _resolve_persona_from_request(request)
    ctx = _safe_get_context(persona)
    if ctx is None:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("update_persona_profile: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        result = await _do_update_persona_profile(persona, ctx, body)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
    # 最終防衛線
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return JSONResponse({"error": "Internal server error"}, status_code=500)
