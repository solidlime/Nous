"""Chat tab package — integrates all chat sub-modules."""

from .chat_layout import (
    render_chat_layout_prefix,
    render_chat_layout_suffix,
    render_chat_main,
    render_chat_shell,
)
from .chat_memory_panel import render_chat_memory_panel
from .chat_sidebar import render_chat_sidebar

__all__ = [
    "render_chat_tab",
    "render_chat_shell",
    "render_chat_inner",
    "render_chat_layout_prefix",
    "render_chat_layout_suffix",
    "render_chat_main",
]


def render_chat_inner(persona: str = "") -> str:
    """v4 lazy body: everything that goes inside #chat-layout.

    /api/chat/{persona}/layout がこれだけを返し、chat.chunk.js が
    SSR 済みの shell（#chat-layout 空）に注入する。wrapper・資産タグは
    含まない（innerHTML では実行・適用されないため）。
    """
    _ = persona  # 将来の persona 別 inner 用に引数だけ残す
    return "".join(
        [
            render_chat_memory_panel(),
            render_chat_main(),
            render_chat_sidebar(),
        ]
    )


def render_chat_tab(persona: str = "") -> str:
    """Return the HTML for the Chat tab (integrated from sub-modules)."""
    return "".join(
        [
            render_chat_layout_prefix(persona),
            render_chat_memory_panel(),
            render_chat_main(),
            render_chat_sidebar(),
            render_chat_layout_suffix(),
        ]
    )
