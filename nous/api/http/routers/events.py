from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, StreamingResponse

from nous.api.http.deps import _resolve_persona_from_request, _safe_get_context
from nous.application.event_bus import (
    EVENT_BODY_STATE_CHANGED,
    EVENT_CONTEXT_UPDATED,
    EVENT_EMOTION_CHANGED,
    EVENT_EVENTS_INGESTED,
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_DELETED,
    EVENT_MEMORY_UPDATED,
    SESSION_ROLLBACK,
)
from nous.domain.memory.session_event import SessionEvent
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

_ALL_EVENT_TYPES = frozenset(
    {
        EVENT_MEMORY_CREATED,
        EVENT_MEMORY_UPDATED,
        EVENT_MEMORY_DELETED,
        EVENT_CONTEXT_UPDATED,
        EVENT_EMOTION_CHANGED,
        EVENT_BODY_STATE_CHANGED,
        SESSION_ROLLBACK,
    }
)


def register_events_routes(mcp) -> None:
    """Register SSE events endpoint."""

    @mcp.custom_route("/api/events/{persona}", methods=["GET"])
    async def events_sse(request: Request) -> StreamingResponse:
        """SSE streaming endpoint for real-time event delivery.

        Query params:
            topics: comma-separated event type prefixes (e.g. "memory,context")
                    If omitted, all event types are delivered.
        """
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if not ctx:

            async def not_found():
                yield f"event: error\ndata: {json.dumps({'message': 'Persona not found'})}\n\n"

            return StreamingResponse(not_found(), media_type="text/event-stream")

        # Parse topic filter
        topics_param = request.query_params.get("topics", "")
        topic_prefixes = [t.strip() for t in topics_param.split(",") if t.strip()] if topics_param else []

        # Determine which event types to subscribe to
        if topic_prefixes:
            subscribed_events = {
                et for et in _ALL_EVENT_TYPES if any(et.startswith(tp) or et == tp for tp in topic_prefixes)
            }
        else:
            subscribed_events = set(_ALL_EVENT_TYPES)

        queue: asyncio.Queue = asyncio.Queue()

        # Create subscriber handler
        async def on_event(event_type: str, data: dict):
            if event_type in subscribed_events:
                await queue.put((event_type, data))

        # Subscribe to EventBus
        for et in subscribed_events:
            ctx.event_bus.subscribe(et, on_event)

        async def event_stream():
            try:
                # Initial connection confirmation
                yield "event: connected\ndata: {}\n\n"

                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event_type, data = await asyncio.wait_for(queue.get(), timeout=15.0)
                        payload = json.dumps(data, ensure_ascii=False, default=str)
                        yield f"event: {event_type}\ndata: {payload}\n\n"
                    except TimeoutError:
                        # Keepalive comment (SSE spec: lines starting with : are comments)
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                pass
            # SSEストリーミング中の非致命的エラー
            except Exception as e:
                logger.debug("SSE stream error for persona '%s': %s", persona, e)
            finally:
                # Unsubscribe on disconnect
                for et in subscribed_events:
                    ctx.event_bus.unsubscribe(et, on_event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ------------------------------------------------------------------
    # POST /api/events/ingest — Plugin用HTTP取り込みAPI
    # ------------------------------------------------------------------

    @mcp.custom_route("/api/events/ingest", methods=["POST"])
    async def events_ingest(request: Request) -> JSONResponse:
        """Ingest session events from external plugins via HTTP POST.

        Accepts JSON body with:
        {
            \"session_id\": \"sess_abc\",
            \"persona\": \"herta\",
            \"events\": [
                {
                    \"type\": \"tool_call\",
                    \"timestamp\": \"2026-06-12T22:30:00+09:00\",
                    \"summary\": \"memory_create: remembered something\",
                    \"detail\": null,
                    \"metadata\": {\"tool_name\": \"memory_create\"}
                }
            ]
        }
        """
        # 1. Parse JSON body
        try:
            body: dict[str, Any] = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        # 2. Extract required fields
        session_id = body.get("session_id")
        persona = body.get("persona")
        raw_events: list[dict[str, Any]] | None = body.get("events")

        if not persona or not isinstance(persona, str):
            return JSONResponse({"error": "Missing or invalid 'persona'"}, status_code=400)
        if not session_id or not isinstance(session_id, str):
            return JSONResponse({"error": "Missing or invalid 'session_id'"}, status_code=400)
        if not isinstance(raw_events, list):
            return JSONResponse({"error": "Missing or invalid 'events' (expected list)"}, status_code=400)

        # 3. Get AppContext for the persona
        ctx = _safe_get_context(persona)
        if not ctx:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        # 4. Plugin API authentication
        plugin_cfg = ctx.settings.plugin
        if not plugin_cfg.enabled:
            return JSONResponse({"error": "Plugin API is disabled"}, status_code=403)
        if not plugin_cfg.api_key:
            return JSONResponse({"error": "Plugin API misconfigured: api_key not set"}, status_code=500)
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)
        token = auth_header.removeprefix("Bearer ").strip()
        if token != plugin_cfg.api_key:
            return JSONResponse({"error": "Invalid API key"}, status_code=401)

        # 5. Ensure database schema exists (session_events table)
        db = ctx.connection.get_memory_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                persona TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, timestamp)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_session_events_persona ON session_events(persona, timestamp)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_session_events_type ON session_events(event_type, timestamp)")
        db.commit()

        # 6. Process events
        repo = SessionEventRepository(ctx.connection)
        inserted = 0
        skipped = 0
        for ev in raw_events:
            if not isinstance(ev, dict):
                skipped += 1
                logger.warning("Skipping non-dict event entry in ingest for persona '%s'", persona)
                continue

            event_type = ev.get("type", "").strip()
            summary = ev.get("summary", "").strip()
            if not event_type or not summary:
                skipped += 1
                logger.warning("Skipping event with missing type/summary for session '%s'", session_id)
                continue

            # Parse timestamp (optional — defaults to now)
            raw_ts = ev.get("timestamp")
            if raw_ts:
                try:
                    timestamp = datetime.fromisoformat(raw_ts)
                except (ValueError, TypeError):
                    skipped += 1
                    logger.warning("Skipping event with invalid timestamp '%s'", raw_ts)
                    continue
            else:
                timestamp = datetime.now()

            detail = ev.get("detail")
            metadata = ev.get("metadata")

            event = SessionEvent(
                session_id=session_id,
                persona=persona,
                event_type=event_type,
                timestamp=timestamp,
                summary=summary,
                detail=detail,
                metadata=metadata,
            )
            try:
                repo.insert(event)
                inserted += 1
            # イベント単位のエラーはスキップして継続
            except Exception:
                logger.exception("Failed to insert session event for persona '%s'", persona)
                skipped += 1

        # 7. Publish event via EventBus
        try:
            await ctx.event_bus.publish(
                EVENT_EVENTS_INGESTED,
                {
                    "persona": persona,
                    "session_id": session_id,
                    "count": inserted,
                    "skipped": skipped,
                },
            )
        # 公開失敗は非致命的
        except Exception:
            logger.exception("Failed to publish events.ingested event for persona '%s'", persona)

        # 8. Return success response
        return JSONResponse({"status": "ok", "count": inserted, "skipped": skipped})
