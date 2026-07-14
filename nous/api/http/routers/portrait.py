"""Portrait HTTP route — generates persona portrait via configured provider."""

from __future__ import annotations

import base64
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
        """Generate a portrait image for the given persona.

        Query params:
            reference_image: str | None — base64-encoded reference image for img2img.
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

        # Optional reference image from query param (base64)
        reference_image_b64 = request.query_params.get("reference_image")
        reference_image: bytes | None = None
        if reference_image_b64:
            try:
                reference_image = base64.b64decode(reference_image_b64)
            except Exception:
                return JSONResponse(
                    {"ok": False, "error": "Invalid base64 reference_image"},
                    status_code=400,
                )

        service = PortraitGenerationService(
            config=ctx.settings.portrait_gen,
            event_bus=ctx.event_bus,
            equipment_service=ctx.equipment_service,
            comfyui_url_override=chat_config.image_gen_comfyui_url or None,
        )
        result = await service.generate(state_result.value, reference_image=reference_image)
        return JSONResponse(result)

    @mcp.custom_route("/api/portrait/{persona}", methods=["POST"])
    async def generate_portrait(request: Request) -> JSONResponse:
        """Generate a portrait image with optional scene description and reference image.

        Supports two content types:
          - ``application/json``: fields via JSON body
            (scene, equipment_desc, reference_image as base64 string).
          - ``multipart/form-data``: fields via form parts
            (scene, equipment_desc as text; reference_image as file upload).

        Request fields:
            scene: str | None — Optional scene description for LLM synthesis.
            equipment_desc: str | None — Optional equipment/clothing description.
            reference_image: str | file | None — Optional reference image
                (base64 string in JSON, or file upload in multipart).
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

        # Parse request: multipart/form-data or JSON
        scene: str | None = None
        equipment_desc: str | None = None
        reference_image: bytes | None = None

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            _scene_val = form.get("scene")
            if isinstance(_scene_val, str):
                scene = _scene_val
            _eq_val = form.get("equipment_desc")
            if isinstance(_eq_val, str):
                equipment_desc = _eq_val
            ref_file = form.get("reference_image")
            if ref_file is not None and hasattr(ref_file, "read"):
                reference_image = await ref_file.read()  # type: ignore[union-attr]
        else:
            body: dict = {}
            with contextlib.suppress(Exception):
                body = await request.json()  # Empty body is fine

            if isinstance(body, dict):
                scene = body.get("scene")
                equipment_desc = body.get("equipment_desc")
                ref_b64 = body.get("reference_image")
                if isinstance(ref_b64, str) and ref_b64:
                    try:
                        reference_image = base64.b64decode(ref_b64)
                    except Exception:
                        return JSONResponse(
                            {"ok": False, "error": "Invalid base64 reference_image"},
                            status_code=400,
                        )

        service = PortraitGenerationService(
            config=ctx.settings.portrait_gen,
            event_bus=ctx.event_bus,
            equipment_service=ctx.equipment_service,
            comfyui_url_override=chat_config.image_gen_comfyui_url or None,
        )
        result = await service.generate(
            state_result.value,
            scene=scene,
            equipment_desc=equipment_desc,
            reference_image=reference_image,
        )
        return JSONResponse(result)
