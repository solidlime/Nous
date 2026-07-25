"""Chat tab package — integrates all chat sub-modules."""

from .chat_layout import render_chat_layout_prefix, render_chat_layout_suffix, render_chat_main
from .chat_memory_panel import render_chat_memory_panel
from .chat_sidebar import render_chat_sidebar


def render_chat_tab() -> str:
    """Return the HTML for the Chat tab (integrated from sub-modules)."""
    return "".join([
        render_chat_layout_prefix(),
        render_chat_memory_panel(),
        render_chat_main(),
        render_chat_sidebar(),
        render_chat_layout_suffix(),
    ])
