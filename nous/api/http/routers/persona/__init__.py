from __future__ import annotations

from nous.api.http.routers.persona.persona_card import sillytavern_card
from nous.api.http.routers.persona.persona_crud import create_persona, delete_persona, update_persona_profile
from nous.api.http.routers.persona.persona_dashboard import dashboard_data, dashboard_page, dashboard_page_persona
from nous.api.http.routers.persona.persona_health import health, list_personas
from nous.api.http.routers.persona.persona_import import import_conversation

__all__ = ["register_persona_routes"]


def register_persona_routes(mcp) -> None:
    mcp.custom_route("/health", methods=["GET"])(health)
    mcp.custom_route("/api/personas", methods=["GET"])(list_personas)
    mcp.custom_route("/", methods=["GET"])(dashboard_page)
    mcp.custom_route("/dashboard/{persona}", methods=["GET"])(dashboard_page_persona)
    mcp.custom_route("/api/dashboard/{persona}", methods=["GET"])(dashboard_data)
    mcp.custom_route("/api/import-conversation/{persona}", methods=["POST"])(import_conversation)
    mcp.custom_route("/api/personas", methods=["POST"])(create_persona)
    mcp.custom_route("/api/personas/{persona}", methods=["DELETE"])(delete_persona)
    mcp.custom_route("/api/personas/{persona}/card.png", methods=["GET"])(sillytavern_card)
    mcp.custom_route("/api/personas/{persona}/profile", methods=["PUT"])(update_persona_profile)
