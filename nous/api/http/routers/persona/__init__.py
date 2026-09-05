from __future__ import annotations

from nous.api.http.routers.persona.persona_crud import create_persona, delete_persona, update_persona_profile
from nous.api.http.routers.persona.persona_dashboard import (
    dashboard_data,
    dashboard_page,
    dashboard_page_persona,
    generate_expressions,
)
from nous.api.http.routers.persona.persona_health import health, list_personas

__all__ = ["register_persona_routes"]


def register_persona_routes(mcp) -> None:
    mcp.custom_route("/health", methods=["GET"])(health)
    mcp.custom_route("/api/personas", methods=["GET"])(list_personas)
    mcp.custom_route("/", methods=["GET"])(dashboard_page)
    mcp.custom_route("/dashboard/{persona}", methods=["GET"])(dashboard_page_persona)
    mcp.custom_route("/api/dashboard/{persona}", methods=["GET"])(dashboard_data)
    mcp.custom_route("/api/personas", methods=["POST"])(create_persona)
    mcp.custom_route("/api/personas/{persona}", methods=["DELETE"])(delete_persona)
    # d5: card.png削除（内部使用ゼロ）。profile PUTはscripts/seed.pyが使用中のため残す。
    mcp.custom_route("/api/personas/{persona}/profile", methods=["PUT"])(update_persona_profile)
    mcp.custom_route("/api/chat/{persona}/persona/expressions/generate", methods=["POST"])(generate_expressions)
