"""Base layout components for the Nous Dashboard.

Provides the shared HTML head, navigation bar, utility JavaScript,
and the overall page shell that section-specific renderers plug into.
"""

import json

from nous import __version__

# ---------------------------------------------------------------------------
# 1. render_head
# ---------------------------------------------------------------------------


def render_head() -> str:
    """Return the full <head>…</head> block (meta, CDN scripts, all CSS)."""
    return r"""<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nous Dashboard</title>
    <!-- Inter font for non-Apple devices (Apple devices use SF Pro via system stack) -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4" defer></script>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js" defer></script>
    <link href="https://unpkg.com/vis-timeline/styles/vis-timeline-graph2d.min.css" rel="stylesheet" />
    <script src="https://unpkg.com/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js" defer></script>
    <script src="https://unpkg.com/lucide@latest" defer></script>
    <link rel="stylesheet" href="/static/styles/variables.css">
    <link rel="stylesheet" href="/static/styles/reset.css">
    <link rel="stylesheet" href="/static/styles/layout.css">
    <link rel="stylesheet" href="/static/styles/theme.css">
    <link rel="stylesheet" href="/static/styles/components.css">
    <link rel="stylesheet" href="/static/styles/chat.css">
    <link rel="stylesheet" href="/static/styles/chat-mobile.css">
    <!-- Nous Core Modules (Phase 1: Foundation) -->
    <script src="/static/core/namespace.js" defer></script>
    <script src="/static/core/constants.js" defer></script>
    <script src="/static/core/store.js" defer></script>
    <script src="/static/core/dom.js" defer></script>
    <script src="/static/core/time.js" defer></script>
    <script src="/static/core/api.js" defer></script>
    <script src="/static/core/toast.js" defer></script>
    <script src="/static/core/modal.js" defer></script>
    <script src="/static/core/theme.js" defer></script>
    <script src="/static/core/sse.js" defer></script>
    <!-- UI Components (Phase 5) — registered as N.Components.* -->
    <script src="/static/components/skeleton.js" defer></script>
    <script src="/static/components/memory-card.js" defer></script>
    <script src="/static/components/chart.js" defer></script>
    <!-- Base application shell — must load before feature scripts -->
    <script src="/static/base.js" defer></script>
    <!-- Chat modules (Phase 3) -->
    <script src="/static/chat/chat-core.js" defer></script>
    <script src="/static/chat/chat-settings.js" defer></script>
    <script src="/static/chat/chat-markdown.js" defer></script>
    <script src="/static/chat/chat-send.js" defer></script>
    <script src="/static/chat/chat-history.js" defer></script>
    <script src="/static/chat/chat-memory-panel.js" defer></script>
    <script src="/static/chat/chat-tools.js" defer></script>
    <script src="/static/chat/chat-equipment.js" defer></script>
    <script src="/static/chat/chat-commands.js" defer></script>
    <script src="/static/chat/chat-attachments.js" defer></script>
    <script src="/static/chat/chat-tts.js" defer></script>
    <script src="/static/chat/chat-voice.js" defer></script>
    <!-- Feature page scripts (defer so N.Core is available) -->
    <script src="/static/features/overview/overview-core.js" defer></script>
    <script src="/static/features/overview/overview-stats.js" defer></script>
    <script src="/static/features/overview/overview-charts.js" defer></script>
    <script src="/static/features/overview/overview-context.js" defer></script>
    <script src="/static/features/memories/memories-core.js" defer></script>
    <script src="/static/features/memories/memories-list.js" defer></script>
    <script src="/static/features/memories/memories-search.js" defer></script>
    <script src="/static/features/memories/memories-edit.js" defer></script>
    <script src="/static/features/settings/settings-validation.js" defer></script>
    <script src="/static/features/settings/settings-save.js" defer></script>
    <script src="/static/features/settings/settings-form.js" defer></script>
    <script src="/static/features/settings/settings-core.js" defer></script>
    <script src="/static/features/graph.js" defer></script>
    <script src="/static/features/timeline.js" defer></script>
    <script src="/static/features/activity.js" defer></script>
</head>"""


# ---------------------------------------------------------------------------
# 2. render_nav
# ---------------------------------------------------------------------------


def render_nav(tabs: list[dict]) -> str:
    """Build ``<nav class="tab-bar">`` dynamically from *tabs*.

    Each element in *tabs* is ``{"id": "...", "lucide": "...", "label": "..."}``.
    All tabs are shown directly; the first tab is marked active.
    """

    def _tab_btn(tab: dict, active: bool, extra_cls: str = "") -> str:
        cls = f"tab-btn{' active' if active else ''}{' ' + extra_cls if extra_cls else ''}"
        sel = "true" if active else "false"
        icon_html = f'<i data-lucide="{tab["lucide"]}"></i>' if tab.get("lucide") else tab.get("icon", "")
        return (
            f'<button class="{cls}" data-tab="{tab["id"]}" '
            f'role="tab" aria-selected="{sel}">'
            f"{icon_html} {tab['label']}</button>"
        )

    buttons = [_tab_btn(t, i == 0) for i, t in enumerate(tabs)]

    return '    <nav class="tab-bar" role="tablist">\n        ' + "\n        ".join(buttons) + "\n    </nav>"


# ---------------------------------------------------------------------------
# 3. render_utilities_js
# ---------------------------------------------------------------------------


def render_utilities_js() -> str:
    """Return a ``<script>`` tag loading the shared utility JavaScript.
    Now handled via defer in render_head() — returns empty."""
    return ""


# ---------------------------------------------------------------------------
# 4. render_layout_shell
# ---------------------------------------------------------------------------


def render_layout_shell(nav_html: str, tab_contents: str, tab_js: str, initial_persona: str | None = None) -> str:
    """Compose the full HTML page.

    Uses string concatenation (NOT f-strings) because the embedded
    JavaScript relies on ``${}`` template literals.
    """
    # Inject initial persona as a JS variable so the SPA can pre-select it.
    # json.dumps produces a valid JSON / JS string literal with proper escaping,
    # and the &#x2F; prevents HTML parser from misinterpreting </script> as tag close.
    if initial_persona:
        persona_init_script = (
            '<script>window.__INITIAL_PERSONA__='
            + json.dumps(initial_persona, ensure_ascii=False).replace("</", "<\\/")
            + ';</script>\n'
        )
    else:
        persona_init_script = ""

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja" class="dark">\n' + render_head() + "\n<body>\n"
        '    <a href="#tab-content" class="skip-link">メインコンテンツにスキップ</a>\n'
        "    <!-- Background Orbs -->\n"
        '    <div class="orb orb-1"></div>\n'
        '    <div class="orb orb-2"></div>\n'
        '    <div class="orb orb-3"></div>\n'
        "\n"
        "    <!-- ============================================================\n"
        "         HEADER\n"
        "         ============================================================ -->\n"
        '    <header class="app-header">\n'
        '        <div style="display:flex;align-items:center;gap:10px;">\n'
        '            <span style="font-size:1.6rem;"><i data-lucide="brain"></i></span>\n'
        "            <h1>Nous v" + __version__ + " Dashboard</h1>\n"
        "        </div>\n"
        '        <div class="header-controls">\n'
        '            <span id="sse-status" class="sse-indicator" title="SSE connection status"><i data-lucide="wifi"></i></span>\n'
        '            <select id="persona-select" class="glass-input" title="Select persona">\n'
        '                <option value="">Loading...</option>\n'
        "            </select>\n"
        '            <button id="create-persona-btn" class="glass-btn" title="Create new persona" onclick="openCreatePersonaModal()">\n'
        '              <i data-lucide="user-plus"></i>\n'
        "            </button>\n"
        '            <button id="delete-persona-btn" class="glass-btn" title="Delete current persona" onclick="deleteCurrentPersona()" style="display:none">\n'
        '              <i data-lucide="trash-2"></i>\n'
        "            </button>\n"
        '            <button id="dark-toggle" class="glass-btn" title="Toggle theme"><i data-lucide="moon"></i></button>\n'
        "        </div>\n"
        "    </header>\n"
        "\n" + nav_html + "\n"
        "\n"
        '    <main class="main-content">\n' + tab_contents + "\n"
        "    </main>\n"
        "\n"
        "    <!-- Memory Detail Modal -->\n"
        '    <div id="mem-modal-overlay" class="mem-modal-overlay" onclick="if(event.target===this)closeMemModal()">\n'
        '        <div class="mem-modal" id="mem-modal-content"></div>\n'
        "    </div>\n"
        "\n"
        "    <!-- Toast container -->\n"
        '    <div id="toast-container" class="toast-container" role="status" aria-live="polite" aria-atomic="true"></div>\n'
        "\n" + persona_init_script + "\n"
        "</body>\n"
        "</html>"
    )
