"""MCP tools for LLM-driven persona portrait generation.

Provides the ``persona_portrait`` tool which accepts an LLM-provided scene
description (and optional style hint) and generates a portrait image via the
configured provider (ComfyUI / DALL-E / Stability).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
from nous.domain.chat_config import ChatConfigRepository

logger = logging.getLogger(__name__)


async def _tool_persona_portrait_with_scene(
    ctx: AppContext,
    persona: str,
    scene: str,
    style: str | None = None,
    reference_image: str | None = None,
) -> str:
    """Generate a portrait image for the current persona using an LLM scene.

    Parameters
    ----------
    ctx : AppContext
        Application context with services and settings.
    persona : str
        Persona name.
    scene : str
        LLM-provided scene description (e.g. "at the beach watching sunset").
    style : str | None
        Optional art style hint (e.g. "anime", "watercolor", "oil painting").
        When provided the style is incorporated into the prompt.
    reference_image : str | None
        Optional base64-encoded reference image for img2img generation.

    Returns
    -------
    str
        JSON string with ``{"image_base64": "...", "revised_prompt": "..."}``
        on success, or ``{"ok": False, "error": "..."}`` on failure.
    """
    try:
        # 0. Enabled check — ChatConfig (per-persona)
        chat_config = ChatConfigRepository(ctx.connection.get_memory_db()).get(persona)
        if not chat_config.portrait_enabled:
            return json.dumps(
                {"ok": False, "error": "Portrait generation is disabled for this persona"},
                ensure_ascii=False,
            )

        state_result = ctx.persona_service.get_context(persona)
        if not state_result.is_ok:
            return json.dumps({"ok": False, "error": str(state_result.error)}, ensure_ascii=False)

        persona_state = state_result.value
        config = ctx.settings.portrait_gen

        # Incorporate style into scene if provided
        effective_scene = scene
        if style:
            effective_scene = f"{scene}, {style} style"

        # Decode reference_image if provided (base64 → bytes)
        ref_bytes: bytes | None = None
        if reference_image:
            try:
                ref_bytes = base64.b64decode(reference_image)
            except Exception:
                return json.dumps(
                    {"ok": False, "error": "Invalid base64 reference_image"},
                    ensure_ascii=False,
                )

        from nous.application.portrait.service import PortraitGenerationService

        service = PortraitGenerationService(
            config,
            equipment_service=ctx.equipment_service,
            comfyui_url_override=chat_config.image_gen_comfyui_url or None,
        )
        result = await service.generate(persona_state, scene=effective_scene, reference_image=ref_bytes)

        # Map service result to tool output format
        return json.dumps(
            {
                "image_base64": result.get("image_base64", ""),
                "revised_prompt": result.get("prompt", effective_scene),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
