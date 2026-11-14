from nous.api.http.routers.admin import register_admin_routes
from nous.api.http.routers.chat import register_chat_routes
from nous.api.http.routers.events import register_events_routes
from nous.api.http.routers.image_gen import register_image_gen_routes
from nous.api.http.routers.item import register_item_routes
from nous.api.http.routers.memory import register_memory_routes
from nous.api.http.routers.metrics import register_metrics_routes
from nous.api.http.routers.persona import register_persona_routes
from nous.api.http.routers.project_context import register_project_context_routes
from nous.api.http.routers.search import register_search_routes
from nous.api.http.routers.session_events import register_session_events_routes
from nous.api.http.routers.skills import register_skills_routes
from nous.api.http.routers.tts import register_tts_routes
from nous.api.http.routers.wiki import register_wiki_routes

__all__ = [
    "register_admin_routes",
    "register_chat_routes",
    "register_events_routes",
    "register_image_gen_routes",
    "register_item_routes",
    "register_memory_routes",
    "register_metrics_routes",
    "register_persona_routes",
    "register_project_context_routes",
    "register_search_routes",
    "register_session_events_routes",
    "register_skills_routes",
    "register_tts_routes",
    "register_wiki_routes",
]
