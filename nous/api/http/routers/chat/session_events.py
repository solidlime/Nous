"""Session Events API – paginated event query for the Activity feed."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.compat import envelope_error, envelope_ok, legacy_requested
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


async def _begin_notes(ctx, persona: str) -> list[str]:
    """begin の notes（沈黙の間 #37）。失敗しても begin は落とさない。"""
    from nous.application.session.session_notes import fill_silence

    notes: list[str] = []
    try:
        warning = await fill_silence(ctx, persona, getattr(ctx.settings, "session_silence_hours", None))
        if warning:
            notes.append(warning)
    except Exception as e:  # noqa: BLE001 — begin を守る
        logger.warning("session_begin: notes failed persona=%s: %s", persona, e)
        notes.append(f"warning: notes skipped: {e}")
    return notes


def register_session_events_routes(mcp) -> None:
    """Register ``GET /api/session-events/{persona}`` and ``POST /api/session/{persona}/begin``."""

    @mcp.custom_route("/api/session/{persona}/begin", methods=["POST"])
    async def session_begin(request: Request):
        """Session-start entry (audit M8): same core as the MCP ``session_begin`` tool.

        New format is the envelope; ``?compat=legacy`` returns the pre-v4 flat
        dict (``{ok, result}``) that ``get_context`` used to emit.
        """
        from nous.api.mcp._envelope import ToolErrorCode
        from nous.api.mcp._tools_persona import _tool_session_begin

        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return envelope_error(ToolErrorCode.NOT_FOUND, f"Persona '{persona}' not found", 404)
        flat = await _tool_session_begin(ctx, persona, project=request.query_params.get("project") or None)
        # 失敗時にも legacy の非推奨 WARNING を出すため、判定はガードより先に1回だけ評価する。
        legacy = legacy_requested(request, "POST /api/session/{persona}/begin")
        # fail-closed: ok が無い/偽なら失敗。MCP 側 tools.py の `if result.get("ok")` と形を揃える。
        # error は DomainError（Exception）で来るので str() しないと JSONResponse が落ちる（tools.py:39 と同じ）。
        if not flat.get("ok"):
            return envelope_error(ToolErrorCode.INTERNAL, str(flat.get("error") or "session begin failed"), 500)
        notes = await _begin_notes(ctx, persona)
        if legacy:
            return JSONResponse({**flat, "notes": notes})
        return JSONResponse(envelope_ok({"context": flat.get("result", ""), "notes": notes}))

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
