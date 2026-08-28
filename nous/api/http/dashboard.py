"""Nous v3 Dashboard - Single Page Application.

A modular glassmorphism dashboard for managing persona memories,
analytics, settings, and administration. Each tab is defined in
its own module under ``sections/``.
"""

from .sections.activity import render_activity_js, render_activity_tab
from .sections.base import render_layout_shell, render_nav
from .sections.chat import render_chat_tab
from .sections.knowledge_graph import render_graph_js, render_graph_tab
from .sections.memories import render_memories_js, render_memories_tab
from .sections.overview import render_overview_js, render_overview_tab
from .sections.settings import render_settings_js, render_settings_tab
from .sections.timeline import render_timeline_js, render_timeline_tab


def render_dashboard(persona: str | None = None) -> str:
    """Return the complete HTML string for the SPA dashboard."""
    tabs = [
        {"id": "overview", "lucide": "layout-dashboard", "label": "Overview"},
        {"id": "memories", "lucide": "brain", "label": "Memories"},
        {"id": "chat", "lucide": "message-circle", "label": "Chat"},
        {"id": "activity", "lucide": "activity", "label": "Activity"},
        {"id": "settings", "lucide": "settings", "label": "Settings"},
        {"id": "timeline", "lucide": "clock", "label": "Timeline"},
        {"id": "graph", "lucide": "share-2", "label": "Graph"},
    ]

    nav_html = render_nav(tabs)

    tab_contents = "\n".join(
        [
            render_overview_tab(),
            render_memories_tab(),
            render_timeline_tab(),
            render_graph_tab(),
            render_chat_tab(persona or ""),
            render_activity_tab(),
            render_settings_tab(),
        ]
    )

    tab_js = "\n".join(
        filter(
            None,
            [
                render_overview_js(),
                render_memories_js(),
                render_timeline_js(),
                render_graph_js(),
                render_activity_js(),
                render_settings_js(),
            ],
        )
    )

    import re

    html = render_layout_shell(nav_html, tab_contents, tab_js)
    # Clean lone surrogates that break UTF-8 encoding (U+D800-U+DFFF)
    return re.sub(r"[\ud800-\udfff]", "\ufffd", html)
