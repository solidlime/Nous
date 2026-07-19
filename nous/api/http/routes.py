from __future__ import annotations

from nous.api.http.routers import (
    register_admin_routes,
    register_chat_routes,
    register_events_routes,
    register_image_gen_routes,
    register_item_routes,
    register_memory_routes,
    register_persona_routes,
    register_search_routes,
    register_session_events_routes,
    register_skills_routes,
    register_tts_routes,
)


def register_http_routes(mcp) -> None:
    """Register HTTP routes on the FastMCP server."""
    register_persona_routes(mcp)
    register_memory_routes(mcp)
    register_search_routes(mcp)
    register_item_routes(mcp)
    register_admin_routes(mcp)
    register_chat_routes(mcp)
    register_skills_routes(mcp)
    register_tts_routes(mcp)
    register_events_routes(mcp)
    register_session_events_routes(mcp)
    register_image_gen_routes(mcp)
