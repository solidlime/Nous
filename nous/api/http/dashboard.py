"""Nous v3 Dashboard - Single Page Application.

A modular glassmorphism dashboard for managing persona memories,
analytics, settings, and administration. Each tab is defined in
its own module under ``sections/``.
"""

from .sections.activity import render_activity_tab
from .sections.base import render_layout_shell, render_lazy_tab, render_nav
from .sections.chat import render_chat_shell
from .sections.knowledge_graph import render_graph_tab
from .sections.overview import render_overview_tab
from .sections.projects import render_project_tab
from .sections.settings import render_settings_tab
from .sections.timeline import render_timeline_tab
from .sections.wiki import render_wiki_tab


def render_dashboard(persona: str | None = None) -> str:
    """Return the complete HTML string for the SPA dashboard."""
    # Single source of truth for all tab wiring (#93): the nav generator
    # (render_nav), the tab loader (base.js loadTab) and the skeleton switch
    # (skeleton.js show) all read from this list — add a tab here only.
    tabs: list[dict] = [
        {
            "id": "overview",
            "lucide": "layout-dashboard",
            "label": "Overview",
            "loader": "Nous.Features.Overview.loadOverview",
        },
        {"id": "memories", "lucide": "brain", "label": "Memories", "loader": "Nous.Features.Memories.loadMemories"},
        {
            "id": "wiki",
            "lucide": "book-open",
            "label": "Wiki",
            "loader": "Nous.Features.Wiki.loadWiki",
            "selfManaged": True,
        },
        {
            "id": "projects",
            "lucide": "folder-kanban",
            "label": "Projects",
            "loader": "Nous.Features.Projects.loadProject",
            "selfManaged": True,
        },
        {
            "id": "chat",
            "lucide": "message-circle",
            "label": "Chat",
            "loader": "Nous.Chat.core.loadChat",
            "selfManaged": True,
        },
        {
            "id": "activity",
            "lucide": "activity",
            "label": "Activity",
            "loader": "Nous.Features.Activity.loadActivity",
            "loaderArgs": [True],
            "selfManaged": True,
        },
        {"id": "settings", "lucide": "settings", "label": "Settings", "loader": "Nous.Features.Settings.loadSettings"},
        {
            "id": "timeline",
            "lucide": "clock",
            "label": "Timeline",
            "loader": "Nous.Features.Timeline.loadTimeline",
            "selfManaged": True,
        },
        {
            "id": "graph",
            "lucide": "share-2",
            "label": "Graph",
            "loader": "Nous.Features.Graph.loadGraph",
            "selfManaged": True,
        },
    ]

    nav_html = render_nav(tabs)

    # v4: overview + 6 small tabs are server-rendered (~11KB total markup).
    # Chat ships its shell only (~1KB: wrapper + tab-head + empty #chat-layout);
    # the 75KB inner (memory + main + sidebar) comes from
    # /api/chat/{persona}/layout and is injected by chat.chunk.js BEFORE any
    # chat script runs (innerHTML never executes <script>, and lazy scripts
    # would bind to missing DOM — BLOCK-1/2).
    _ssr_tabs = {
        "overview": render_overview_tab,
        "wiki": render_wiki_tab,
        "projects": render_project_tab,
        "activity": render_activity_tab,
        "settings": render_settings_tab,
        "timeline": render_timeline_tab,
        "graph": render_graph_tab,
        "chat": lambda: render_chat_shell(persona or ""),
    }
    tab_contents = "\n".join([(fn() if (fn := _ssr_tabs.get(t["id"])) else render_lazy_tab(t["id"])) for t in tabs])

    import re

    html = render_layout_shell(nav_html, tab_contents)
    # Clean lone surrogates that break UTF-8 encoding (U+D800-U+DFFF)
    return re.sub(r"[\ud800-\udfff]", "\ufffd", html)
