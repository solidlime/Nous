"""Base layout components for the Nous Dashboard.

Provides the shared HTML head, navigation bar, utility JavaScript,
and the overall page shell that section-specific renderers plug into.
"""

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
    <script src="https://cdn.tailwindcss.com" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4" defer></script>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js" defer></script>
    <link href="https://unpkg.com/vis-timeline/standalone/umd/vis-timeline-graph2d.min.css" rel="stylesheet" />
    <script src="https://unpkg.com/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js" defer></script>
    <script src="https://unpkg.com/lucide@latest" defer></script>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/chat.js" defer></script>
    <script src="/static/portrait.js" defer></script>
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
    """Return a ``<script>`` tag loading the shared utility JavaScript."""
    return '<script src="/static/base.js"></script>'


# ---------------------------------------------------------------------------
# 4. render_layout_shell
# ---------------------------------------------------------------------------


def render_layout_shell(nav_html: str, tab_contents: str, tab_js: str, initial_persona: str | None = None) -> str:
    """Compose the full HTML page.

    Uses string concatenation (NOT f-strings) because the embedded
    JavaScript relies on ``${}`` template literals.
    """
    # Inject initial persona as a JS variable so the SPA can pre-select it
    if initial_persona:
        safe_persona = (
            initial_persona.replace("\\", "\\\\").replace('"', '\\"').replace("<", "").replace(">", "").replace("&", "")
        )
        persona_init_script = '<script>window.__INITIAL_PERSONA__="' + safe_persona + '";</script>\n'
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
        '            <select id="persona-select" class="glass-input" title="Select persona">\n'
        '                <option value="">Loading...</option>\n'
        "            </select>\n"
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
        "\n" + persona_init_script + render_utilities_js() + "\n"
        "<script>\n" + tab_js + "\n"
        "</script>\n"
        "</body>\n"
        "</html>"
    )
