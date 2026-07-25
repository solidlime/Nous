from __future__ import annotations

import io
import json as _json
from typing import TYPE_CHECKING

from PIL import Image, PngImagePlugin
from starlette.responses import JSONResponse, Response

from nous.api.http.routers.persona.persona_helpers import _resolve_request
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

    from nous.domain.persona.entities import PersonaState

logger = get_logger(__name__)


async def _do_sillytavern_card(persona: str, ctx) -> bytes:
    """Build SillyTavern card PNG bytes from persona state."""
    state_result = ctx.persona_service.get_context(persona)
    if not state_result.is_ok:
        raise ValueError("Failed to get persona context")
    return _build_sillytavern_card(state_result.value)


async def sillytavern_card(request: Request) -> Response:
    """GET /api/personas/{persona}/card.png — export SillyTavern character card."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        png_bytes = await _do_sillytavern_card(persona, ctx)
        return Response(content=png_bytes, media_type="image/png")
    except ValueError:
        return JSONResponse({"error": "Internal server error"}, status_code=500)


def _build_sillytavern_card(state: PersonaState) -> bytes:
    """Build a SillyTavern v3 character card PNG from a PersonaState.

    Creates a 400×600 PNG with a solid background colored by the current
    emotion and embeds the ``chara`` JSON in a ``tEXt`` chunk per the
    SillyTavern v3 spec.
    """
    emotion_colors: dict[str, str] = {
        "joy": "#FFD700",
        "sadness": "#6495ED",
        "anger": "#FF4500",
        "fear": "#9370DB",
        "surprise": "#FF69B4",
        "disgust": "#228B22",
        "trust": "#20B2AA",
        "anticipation": "#FF8C00",
        "love": "#FF1493",
        "neutral": "#A9A9A9",
    }

    pi = state.persona_info or {}
    display_name = pi.get("nickname") or state.persona

    color_hex = emotion_colors.get(state.emotion, "#A9A9A9")
    # Convert hex to RGBA tuple
    color_rgba = tuple(int(color_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) + (255,)

    img = Image.new("RGBA", (400, 600), color_rgba)

    card_data: dict = {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": display_name,
            "description": pi.get("description") or pi.get("personality", ""),
            "personality": pi.get("personality_summary", ""),
            "scenario": pi.get("scenario", ""),
            "first_mes": pi.get("greeting") or pi.get("first_message", f"こんにちは、{display_name}です。"),
            "mes_example": pi.get("example_dialogue", ""),
            "creator_notes": "",
            "system_prompt": pi.get("system_prompt", ""),
            "post_history_instructions": "",
            "tags": [],
            "creator": "Nous",
            "character_version": "1.0",
            "extensions": {},
        },
    }

    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("chara", _json.dumps(card_data, ensure_ascii=False))

    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png_info)
    return buf.getvalue()
