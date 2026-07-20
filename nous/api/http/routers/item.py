from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.routers._error_handlers import error_from_result

from nous.api.http.deps import (
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def _item_to_dict(it) -> dict:
    d = asdict(it)
    for k in ("created_at", "updated_at"):
        if k in d and d[k] is not None:
            d[k] = d[k].isoformat()
    return d


def register_item_routes(mcp) -> None:
    @mcp.custom_route("/api/items/{persona}", methods=["GET"])
    async def list_items(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.equipment_service.search_items()
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"persona": persona, "items": [_item_to_dict(it) for it in result.value]})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/items/{persona}", methods=["POST"])
    async def add_item(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        item_name = body.get("item_name")
        if not item_name:
            return JSONResponse({"error": "Field 'item_name' is required"}, status_code=400)
        try:
            result = ctx.equipment_service.add_item(
                item_name,
                body.get("category"),
                body.get("description"),
                body.get("quantity", 1),
                body.get("tags"),
            )
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"status": "ok", "item_name": item_name}, status_code=201)
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/items/{persona}/equip", methods=["POST"])
    async def equip_items(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(body, dict) or not body:
            return JSONResponse({"error": "Body must be a non-empty dict of {slot: item_name}"}, status_code=400)
        auto_add = body.pop("auto_add", True)
        if not body:
            return JSONResponse({"error": "No equipment slots provided"}, status_code=400)
        try:
            result = ctx.equipment_service.equip(body, auto_add)
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"status": "ok", "equipped": body})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/items/{persona}/unequip", methods=["POST"])
    async def unequip_items(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        slots = body.get("slots", [])
        if isinstance(slots, str):
            slots = [slots]
        if not slots:
            return JSONResponse({"error": "Field 'slots' is required"}, status_code=400)
        try:
            result = ctx.equipment_service.unequip(slots)
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"status": "ok", "unequipped": slots})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/items/{persona}/{item_name}", methods=["PUT"])
    async def update_item(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        item_name = request.path_params.get("item_name", "")
        if not item_name:
            return JSONResponse({"error": "Item name is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        allowed = {"category", "description", "quantity", "tags", "item_name"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            return JSONResponse({"error": "No valid fields to update"}, status_code=400)
        try:
            result = ctx.equipment_service.update_item(item_name, **updates)
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"status": "ok", "item_name": item_name})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/items/{persona}/{item_name}", methods=["DELETE"])
    async def delete_item(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        item_name = request.path_params.get("item_name", "")
        if not item_name:
            return JSONResponse({"error": "Item name is required"}, status_code=400)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            result = ctx.equipment_service.remove_item(item_name)
            if not result.is_ok:
                return error_from_result(result)
            return JSONResponse({"status": "ok", "deleted": item_name})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)
