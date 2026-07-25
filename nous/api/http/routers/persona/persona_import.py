from __future__ import annotations

import json
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.routers.persona.persona_helpers import _resolve_request
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


async def _do_import_conversation(persona: str, ctx, file_path: str) -> dict:
    """Import conversation file into persona memory. Returns count dict."""
    from nous.migration.importers.convo_importer import parse_conversation_file

    messages = parse_conversation_file(file_path)
    if not messages:
        return {"imported": 0, "skipped": 0, "message": "No importable messages found"}
    imported = 0
    skipped = 0
    for msg in messages:
        res = await ctx.memory_service.create_memory(
            content=msg.content,
            importance=0.4,
            emotion="neutral",
            emotion_intensity=0.0,
            tags=[],
            privacy_level="internal",
            source_context="convo_import",
        )
        if res.is_ok:
            if ctx.vector_store:
                await ctx.vector_store.upsert(persona, res.value.key, msg.content)
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped, "message": f"Imported {imported} messages"}


async def import_conversation(request: Request) -> JSONResponse:
    """POST /api/import-conversation/{persona} — upload conversation file."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        logger.exception("import_conversation: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    file_path = (body.get("file_path") or "").strip()
    if not file_path:
        return JSONResponse({"error": "Field 'file_path' is required"}, status_code=400)
    try:
        result = await _do_import_conversation(persona, ctx, file_path)
    except FileNotFoundError:
        return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)
    except ValueError:
        return JSONResponse({"error": "Unsupported or invalid conversation file format"}, status_code=422)
    # 最終防衛線
    except Exception as exc:
        logger.exception("Conversation parse error: %s", exc)
        return JSONResponse({"error": "Failed to parse conversation file"}, status_code=500)
    return JSONResponse(result)
