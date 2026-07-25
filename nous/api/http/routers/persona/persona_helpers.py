from __future__ import annotations

from typing import TYPE_CHECKING

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context

if TYPE_CHECKING:
    from starlette.requests import Request


def _resolve_request(request: Request):
    """Return (persona, ctx) or (persona, None)."""
    persona = _resolve_persona_from_request(request)
    ctx = _safe_get_context(persona)
    return persona, ctx
