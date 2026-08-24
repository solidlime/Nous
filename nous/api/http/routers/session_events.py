"""Session Events API – paginated event query for the Activity feed."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)


def _parse_int_param(params, name: str, default: int) -> int:
    """クエリパラメータを int で取得。不正値はデフォルトにフォールバック（500 を返さない）。"""
    try:
        return int(params.get(name, default))
    except (TypeError, ValueError):
        return default


def register_session_events_routes(mcp) -> None:
    """Register ``GET /api/session-events/{persona}``."""

    @mcp.custom_route("/api/session-events/{persona}", methods=["GET"])
    async def get_session_events(request: Request):
        """Return paginated session events for a persona.

        Query params:
            limit  (int, default 50)
            offset (int, default 0)
            event_type (str, optional) – e.g. 'tool.called', 'chat.message'
            order  (str, default 'desc') – 'asc' or 'desc'
        """
        persona = _resolve_persona_from_request(request)
        limit = _parse_int_param(request.query_params, "limit", 50)
        offset = _parse_int_param(request.query_params, "offset", 0)
        event_type = request.query_params.get("event_type") or None
        order = request.query_params.get("order", "desc")
        if order not in ("asc", "desc"):
            order = "desc"

        limit = min(max(limit, 1), 500)

        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "persona not found"}, status_code=404)

        repo = SessionEventRepository(ctx.connection)
        events, total = repo.get_by_persona_paginated(
            persona=persona,
            limit=limit,
            offset=offset,
            event_type=event_type,
            order=order,
        )

        return JSONResponse(
            {
                "events": [
                    {
                        "id": e.id,
                        "session_id": e.session_id,
                        "event_type": e.event_type,
                        "timestamp": e.timestamp.isoformat(),
                        "summary": e.summary,
                        "detail": e.detail,
                        "metadata": e.metadata,
                    }
                    for e in events
                ],
                "total": total,
                "has_more": offset + limit < total,
            }
        )
