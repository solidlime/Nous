import html
import json

from nous import __version__

# ---------------------------------------------------------------------------
# 0. Lazy manifest — single source of truth for everything off the first-paint
#    path (v4). static/core/ready.js reads this tag and fetches a tab's sources
#    the first time the tab is opened.
# ---------------------------------------------------------------------------
LAZY_MANIFEST: dict = {
    "v": 4,
    "css": "/static/styles/tabs-lazy.css",
    "deps": {
        "chart": "https://cdn.jsdelivr.net/npm/chart.js@4",
        "marked": "https://cdn.jsdelivr.net/npm/marked@12/marked.min.js",
        "dompurify": "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js",
        "vis-network": "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js",
        "vis-timeline": "https://unpkg.com/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js",
        "vis-timeline-css": "https://unpkg.com/vis-timeline/styles/vis-timeline-graph2d.min.css",
        "lucide": "/static/vendor/lucide.min.js",
    },
    # loaded before any tab's own sources
    "base": ["lucide", "marked", "dompurify"],
    # cores that are not in shell.js but are shared by tabs
    "shared": [
        "/static/core/constants.js",
        "/static/core/time.js",
        "/static/core/auth.js",
        "/static/core/modal.js",
        "/static/components/chart.js",
        "/static/components/memory-card.js",
        "/static/components/mem-modal.js",
    ],
    "tabs": {
        # #132: no bundling chunk. ready.js already loads ``scripts`` in order,
        # so a tab's own sources are written here directly — the old
        # overview/memories/misc chunks made every visit fetch every tab.
        "overview": {
            "scripts": [
                "/static/features/overview/overview-inventory.js",
                "/static/features/overview/overview-core.js",
                "/static/features/overview/overview-stats.js",
                "/static/features/overview/overview-charts.js",
                "/static/features/overview/overview-context.js",
            ],
            "deps": ["chart"],
        },
        "memories": {
            "scripts": [
                "/static/features/memories/memories-core.js",
                "/static/features/memories/memories-list.js",
                "/static/features/memories/memories-search.js",
                "/static/features/memories/memories-edit.js",
            ],
            "deps": ["chart"],
        },
        "wiki": {"scripts": ["/static/features/wiki.js"]},
        "projects": {"scripts": ["/static/features/projects.js"]},
        # chat owns its 31 sources + the avatar module, so it ships a loader
        "chat": {"scripts": ["/static/chat/chat.chunk.js"], "ready": "Nous.Chat.chunk.load"},
        "activity": {"scripts": ["/static/features/activity.js"]},
        "settings": {
            "scripts": [
                "/static/features/settings/settings-validation.js",
                "/static/features/settings/settings-save.js",
                "/static/features/settings/settings-ui.js",
                "/static/features/settings/settings-form.js",
                "/static/features/settings/settings-core.js",
            ],
        },
        "timeline": {
            "scripts": ["/static/features/timeline.js"],
            "deps": ["vis-timeline", "vis-timeline-css"],
        },
        "graph": {
            "scripts": ["/static/features/graph.js"],
            "deps": ["vis-network"],
        },
    },
}


# ---------------------------------------------------------------------------
# 1. render_head
# ---------------------------------------------------------------------------


def render_head() -> str:
    """Return the full <head> block.

    v4 first paint is one stylesheet (shell-critical.css) and one script
    (shell.js). Fonts (system stack), lucide, the CDN libraries and every
    tab's sources are declared in LAZY_MANIFEST and fetched on demand by
    static/core/ready.js when the tab is first opened.
    """
    # A "</script>" inside the JSON would end the tag early — escape the slash.
    manifest = json.dumps(LAZY_MANIFEST, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return (
        "<head>\n"
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "    <title>Nous Dashboard</title>\n"
        '    <link rel="icon" type="image/png" href="/static/icon.png">\n'
        '    <link rel="apple-touch-icon" href="/static/icon.png">\n'
        "    <!-- v4: first paint carries one CSS and one JS. Everything else --\n"
        "         fonts, lucide, CDN libs, tab sources -- is the lazy manifest. -->\n"
        '    <link rel="stylesheet" href="/static/styles/shell-critical.css">\n'
        '    <script src="/static/shell.js" defer></script>\n'
        '    <script type="application/json" id="lazy-manifest">' + manifest + "</script>\n"
        "</head>"
    )


# ---------------------------------------------------------------------------
# 1b. Lazy tab panels
# ---------------------------------------------------------------------------
# Only the overview tab is server-rendered now; the other panels ship empty and
# their sources fill them on first visit. Two exceptions:
#   * skeleton.js looks for a direct [id$="-content"] child, so the tabs that
#     are not self-managed carry one (memories/settings, plus the panel divs
#     projects/graph already own).
#   * self-managed tabs (wiki/projects/chat/activity/timeline/graph) build
#     their own DOM -- markup inserted here would be replaced by their loader.
_TAB_CONTENT_IDS = {
    "memories": "memories-content",
    "settings": "settings-content",
    "projects": "project-content",
    "graph": "graph-content",
}


def render_lazy_tab(tab: dict) -> str:
    """Return the shell of a lazily loaded tab panel: head + content slot.

    #131: the head is built from the ``dashboard.py`` tab dict (id/lucide/label)
    so a panel that ships no SSR body still shows its title band — the
    alternative (per-tab hand-written shells) is what dropped it for memories.
    """
    tab_id = html.escape(tab["id"], quote=True)
    icon = f'<i data-lucide="{html.escape(tab["lucide"], quote=True)}"></i>' if tab.get("lucide") else ""
    head = (
        '            <div class="tab-head">\n'
        f"                <h2><span>{icon}</span> {html.escape(tab.get('label', ''))}</h2>\n"
        "            </div>"
    )
    content_id = _TAB_CONTENT_IDS.get(tab["id"])
    inner = f'\n            <div id="{content_id}"></div>' if content_id else ""
    return f'        <section id="tab-{tab_id}" class="tab-panel" role="tabpanel">\n{head}{inner}\n        </section>'


# ---------------------------------------------------------------------------
# 2. render_nav
# ---------------------------------------------------------------------------


def render_nav(tabs: list[dict]) -> str:
    """Build ``<nav class="tab-bar">`` dynamically from *tabs*.

    Each element in *tabs* is ``{"id": ..., "lucide": ..., "label": ...}``
    plus optional wiring keys (#93 — dashboard.py is the single source
    of truth): ``loader`` (JS function path), ``loaderArgs`` (JSON array),
    ``selfManaged`` (skip default skeleton swap).
    All tabs are shown directly; the first tab is marked active.
    """

    def _tab_btn(tab: dict, active: bool) -> str:
        cls = f"tab-btn{' active' if active else ''}"
        sel = "true" if active else "false"
        icon_html = f'<i data-lucide="{html.escape(tab["lucide"], quote=True)}"></i>' if tab.get("lucide") else ""
        # #93: tabs are authored in dashboard.py (trusted), but escape anyway —
        # this is an attribute boundary and the docstring accepts any dict.
        attrs = f'data-tab="{html.escape(tab["id"], quote=True)}"'
        if tab.get("loader"):
            attrs += f' data-loader="{html.escape(tab["loader"], quote=True)}"'
        if tab.get("loaderArgs"):
            # #93: loaderArgs is a list — emit a complete JSON array, so the
            # JS side is a plain JSON.parse (no fragment wrapping contract).
            args_json = json.dumps(tab["loaderArgs"], separators=(",", ":"))
            attrs += f' data-loader-args="{html.escape(args_json, quote=True)}"'
        if tab.get("selfManaged"):
            attrs += ' data-self-managed="true"'
        return (
            f'<button class="{cls}" {attrs} '
            f'role="tab" aria-selected="{sel}">'
            f"{icon_html} {html.escape(tab['label'])}</button>"
        )

    buttons = [_tab_btn(t, i == 0) for i, t in enumerate(tabs)]

    return '    <nav class="tab-bar" role="tablist">\n        ' + "\n        ".join(buttons) + "\n    </nav>"


# ---------------------------------------------------------------------------
# 3. render_layout_shell
# ---------------------------------------------------------------------------


def render_layout_shell(nav_html: str, tab_contents: str) -> str:
    """Compose the full HTML page.

    Uses string concatenation (NOT f-strings) because tab HTML strings
    rely on ``${}`` template literals.
    """
    # Rail logo — prepended here (not in render_nav) so render_nav's emitted
    # attribute format stays byte-identical (test_wiki_router.py contract).
    marker = '<nav class="tab-bar" role="tablist">'
    if marker in nav_html:
        nav_html = nav_html.replace(
            marker,
            marker + '\n        <div class="tab-bar-logo" aria-hidden="true">N</div>',
            1,
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja" class="dark">\n' + render_head() + "\n<body>\n"
        '    <a href="#main-content" class="skip-link">メインコンテンツにスキップ</a>\n'
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
        '            <button id="create-persona-btn" class="glass-btn" title="Create new persona">\n'
        '              <i data-lucide="user-plus"></i>\n'
        "            </button>\n"
        '            <button id="delete-persona-btn" class="glass-btn" title="Delete current persona" style="display:none">\n'
        '              <i data-lucide="trash-2"></i>\n'
        "            </button>\n"
        '            <button id="dark-toggle" class="glass-btn" title="Toggle theme"><i data-lucide="moon"></i></button>\n'
        "        </div>\n"
        "    </header>\n"
        "\n"
        '    <div class="app-body">\n' + nav_html + "\n"
        "\n"
        '    <main id="main-content" class="main-content" tabindex="-1">\n' + tab_contents + "\n"
        "    </main>\n"
        "    </div>\n"
        "\n"
        "    <!-- Media viewer overlay — global layer (shared by Chat + Overview,\n"
        "         must stay OUTSIDE tab panels: it is opened cross-tab via\n"
        "         N.Chat.attachments.openViewer) -->\n"
        '    <div id="media-viewer-overlay" data-action="chat-close-viewer">\n'
        '        <button type="button" class="media-viewer-close" data-action="chat-close-viewer" aria-label="プレビューを閉じる">&times;</button>\n'
        '        <div id="media-viewer-inner"></div>\n'
        "    </div>\n"
        "\n"
        "    <!-- Memory Detail Modal -->\n"
        '    <div id="mem-modal-overlay" class="mem-modal-overlay">\n'
        '        <div class="mem-modal" id="mem-modal-content"></div>\n'
        "    </div>\n"
        "\n"
        "    <!-- Create Persona Modal (open/close via .active class toggle,\n"
        "         base.js openCreatePersonaModal) -->\n"
        '    <div id="create-persona-modal" class="ov-modal-overlay" role="dialog" aria-modal="true" aria-label="Create Persona">\n'
        '        <div class="persona-modal-card">\n'
        '            <h2><i data-lucide="user-plus"></i> Create Persona</h2>\n'
        "            <p>Enter a name for the new persona.</p>\n"
        '            <form id="create-persona-form" class="persona-modal-form">\n'
        '                <input id="new-persona-name" type="text" placeholder="e.g. assistant, friend, scholar" class="glass-input" required />\n'
        '                <div class="persona-modal-actions">\n'
        '                    <button type="button" id="create-persona-cancel" class="glass-btn">Cancel</button>\n'
        '                    <button type="submit" class="glass-btn persona-modal-submit">Create</button>\n'
        "                </div>\n"
        "            </form>\n"
        "        </div>\n"
        "    </div>\n"
        "\n"
        "    <!-- Toast container -->\n"
        '    <div id="toast-container" class="toast-container" role="status" aria-live="polite" aria-atomic="true"></div>\n'
        "\n"
        "    <!-- Quick command bar (⌘K target). Global layer: must stay OUTSIDE\n"
        "         .tab-panel — layout.css `contain: paint` would break the fixed\n"
        "         positioning and make it scroll with the panel. -->\n"
        '    <div class="md-cmdbar"><b aria-hidden="true">›</b><input id="md-cmdbar-input" placeholder="ask ..." aria-label="クイックコマンド"><kbd>⌘K</kbd></div>\n'
        "</body>\n"
        "</html>"
    )
