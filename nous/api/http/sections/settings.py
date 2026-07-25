"""Settings tab section for the Nous Dashboard.

Renders the settings configuration panel with live hot-reload support,
source-priority display (env > override > default), settings profiles,
search/filter, field validation, and dependency rules.
"""

from pathlib import Path


def render_settings_tab() -> str:
    """Return the HTML for the Settings tab panel with skeleton loader and inline CSS."""
    return """
        <style>
        .setting-category-card .cat-body { transition: max-height 0.3s ease; overflow: hidden; }
        .setting-diff-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-blue); display: inline-block; }
        .setting-reset-btn { background: rgba(96,165,250,0.1); border: 1px solid rgba(96,165,250,0.2); border-radius: 8px; color: var(--accent-blue); cursor: pointer; font-size: 0.72rem; padding: 4px 10px; transition: all 0.2s; white-space: nowrap; }
        .setting-reset-btn:hover { background: rgba(96,165,250,0.2); }
        .cat-reset-btn { background: rgba(96,165,250,0.08); border: 1px solid rgba(96,165,250,0.15); border-radius: 8px; color: var(--accent-blue); cursor: pointer; font-size: 0.72rem; padding: 3px 10px; transition: all 0.2s; }
        .cat-reset-btn:hover { background: rgba(96,165,250,0.18); }
        .cat-toggle-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 0.9rem; padding: 2px 6px; transition: transform 0.2s; }
        .profile-chip { transition: all 0.2s; }
        .profile-chip:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(var(--accent-blue-rgb), 0.2); }
        </style>
        <!-- ========== SETTINGS TAB ========== -->
        <section id="tab-settings" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="settings"></i></span> Settings</h2>
            </div>
            <div id="settings-content">
                <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
            </div>
        </section>"""


_JS_DIR = Path(__file__).resolve().parent.parent / "static" / "features" / "settings"
_JS = "".join(
    (_JS_DIR / f).read_text(encoding="utf-8")
    for f in ["settings-validation.js", "settings-save.js", "settings-ui.js", "settings-form.js", "settings-core.js"]
)


def render_settings_js() -> str:
    """Return all JavaScript for the Settings tab."""
    return _JS
