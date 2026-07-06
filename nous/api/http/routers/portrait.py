"""Portrait HTTP route — generates persona portrait via configured provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.application.portrait.service import PortraitGenerationService
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_portrait_routes(mcp) -> None:
    """Register portrait generation endpoint."""

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

        service = PortraitGenerationService(
            config=ctx.settings.portrait_gen,
            event_bus=ctx.event_bus,
        )
        result = await service.generate(state_result.value)
        return JSONResponse(result)
