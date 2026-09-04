"""SessionEventRecorder: EventBus subscriber that records MCP tool calls and session events."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from nous.application.event_bus import CHAT_LLM_RESPONSE, CHAT_MESSAGE, SESSION_COMPACT, SESSION_STARTED
from nous.domain.memory.session_event import SessionEvent
from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from nous.application.event_bus import EventBus

logger = logging.getLogger(__name__)


class SessionEventRecorder:
    """Subscribes to EventBus and persists session events to SQLite."""

    def __init__(self, event_bus: EventBus, session_event_repo):
        self._event_bus = event_bus
        self._repo = session_event_repo

    def start(self) -> None:
        """Subscribe to all session-relevant event types."""
        event_types = [
            "tool.called",
            "events.ingested",
            CHAT_MESSAGE,
            CHAT_LLM_RESPONSE,
            SESSION_STARTED,
            SESSION_COMPACT,
        ]
        for event_type in event_types:
            self._event_bus.subscribe(event_type, self._on_event)
        logger.info("SessionEventRecorder started, subscribed to %d event types", len(event_types))

    async def _on_event(self, event_type: str, data: dict) -> None:
        """Handles an event: converts to SessionEvent and persists."""
        try:
            session_id = data.get("session_id", "unknown")
            persona = data.get("persona", "unknown")
            summary = self._build_summary(event_type, data)
            timestamp_str = data.get("timestamp")
            timestamp = get_now()  # fallback
            if timestamp_str:
                from datetime import datetime

                with contextlib.suppress(ValueError, TypeError):
                    timestamp = datetime.fromisoformat(timestamp_str)

            detail = data.get("detail")
            metadata = data.get("metadata")

            event = SessionEvent(
                session_id=session_id,
                persona=persona,
                event_type=event_type,
                summary=summary,
                timestamp=timestamp,
                detail=detail,
                metadata=metadata,
            )
            self._repo.insert(event)
        except Exception as e:
            logger.error("SessionEventRecorder: failed to record event %s: %s", event_type, e)

    def _build_summary(self, event_type: str, data: dict) -> str:
        """Build a human-readable summary from event data."""
        if event_type == "tool.called":
            tool_name = data.get("tool_name", "unknown")
            result = data.get("result_summary", "")
            success = data.get("success", True)
            status = "✓" if success else "✗"
            return f"{tool_name}: {status} {result[:80]}" if result else f"{tool_name}: {status}"
        elif event_type == "events.ingested":
            count = len(data.get("events", []))
            return f"Plugin ingested {count} events"
        elif event_type == CHAT_MESSAGE:
            content = data.get("content", "")
            return f"💬 {content[:100]}"
        elif event_type == CHAT_LLM_RESPONSE:
            content = data.get("content", "")
            return f"🤖 {content[:100]}"
        elif event_type == SESSION_COMPACT:
            before = data.get("before_tokens", 0)
            after = data.get("after_tokens", 0)
            return f"📦 Compressed: {before}→{after} tokens"
        elif event_type == SESSION_STARTED:
            sid = data.get("session_id", "")
            return f"▶ Session started: {sid}"
        return f"{event_type}: {data.get('summary', '')}"
