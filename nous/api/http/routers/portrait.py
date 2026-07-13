"""Portrait HTTP route — generates persona portrait via configured provider."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.application.portrait.service import PortraitGenerationService
from nous.domain.chat_config import ChatConfigRepository
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_portrait_routes(mcp) -> None:
    """Register portrait generation endpoints."""

    @mcp.custom_route("/api/portrait/{persona}", methods=["GET"])
    async def get_portrait(request: Request) -> JSONResponse:
        """Generate a portrait image for the given persona."""
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        state_result = ctx.persona_service.get_context(persona)
        if not state_result.is_ok:
            return JSONResponse({"ok": False, "error": state_result.error}, status_code=500)

        # Enabled check — ChatConfig (per-persona)
        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        if not chat_config.portrait_enabled:
            return JSONResponse(
                {"ok": False, "error": "Portrait generation is disabled for this persona"},
                status_code=403,
            )

        service = PortraitGenerationService(
            config=ctx.settings.portrait_gen,
            event_bus=ctx.event_bus,
            equipment_service=ctx.equipment_service,
        )
        result = await service.generate(state_result.value)
        return JSONResponse(result)

    @mcp.custom_route("/api/portrait/{persona}", methods=["POST"])
    async def generate_portrait(request: Request) -> JSONResponse:
        """Generate a portrait image with optional scene description.

        Request body (JSON):
            scene: str | None — Optional scene description for LLM synthesis.
            equipment_desc: str | None — Optional equipment/clothing description.
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"ok": False, "error": "Persona not found"}, status_code=404)

        state_result = ctx.persona_service.get_context(persona)
        if not state_result.is_ok:
            return JSONResponse({"ok": False, "error": state_result.error}, status_code=500)

        # Enabled check — ChatConfig (per-persona)
        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        if not chat_config.portrait_enabled:
            return JSONResponse(
                {"ok": False, "error": "Portrait generation is disabled for this persona"},
                status_code=403,
            )

        # Parse request body
        body = {}
        with contextlib.suppress(Exception):
            body = await request.json()  # Empty body is fine

        scene = body.get("scene") if isinstance(body, dict) else None
        equipment_desc = body.get("equipment_desc") if isinstance(body, dict) else None

        service = PortraitGenerationService(
            config=ctx.settings.portrait_gen,
            event_bus=ctx.event_bus,
            equipment_service=ctx.equipment_service,
        )
        result = await service.generate(
            state_result.value,
            scene=scene,
            equipment_desc=equipment_desc,
        )
        return JSONResponse(result)
