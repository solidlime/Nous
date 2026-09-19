"""Dashboard section modules for the Nous WebUI."""

from .base import render_head, render_layout_shell, render_nav, render_utilities_js
from .knowledge_graph import render_graph_js, render_graph_tab
from .memories import render_memories_js, render_memories_tab
from .overview import render_overview_js, render_overview_tab
from .settings import render_settings_js, render_settings_tab
from .timeline import render_timeline_js, render_timeline_tab

__all__ = [
    "render_head",
    "render_nav",
    "render_utilities_js",
    "render_layout_shell",
    "render_overview_tab",
    "render_overview_js",
    "render_memories_tab",
    "render_memories_js",
    "render_timeline_tab",
    "render_timeline_js",
    "render_graph_tab",
    "render_graph_js",
    "render_settings_tab",
    "render_settings_js",
]
