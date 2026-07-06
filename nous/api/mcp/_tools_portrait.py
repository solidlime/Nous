"""Portrait generation MCP tool — generates persona portrait via configured provider."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

logger = logging.getLogger(__name__)


async def _tool_persona_portrait(ctx: AppContext, persona: str) -> str:
    """Generate a portrait image for the current persona state.

    Returns JSON with image_base64, prompt, negative_prompt on success,
    or ``{"ok": False, "error": "..."}`` on unexpected failure.
    """
    try:
        state_result = ctx.persona_service.get_context(persona)
        if not state_result.is_ok:
            return json.dumps({"ok": False, "error": str(state_result.error)}, ensure_ascii=False)

        persona_state = state_result.value
        config = ctx.settings.portrait_gen

        from nous.application.portrait.service import PortraitGenerationService

        service = PortraitGenerationService(config)
        result = await service.generate(persona_state)

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
