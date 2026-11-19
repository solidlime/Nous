"""Settings tab section for the Nous Dashboard.

Renders the settings configuration panel with live hot-reload support,
source-priority display (env > override > default), settings profiles,
search/filter, field validation, and dependency rules.
"""


def render_settings_tab() -> str:
    """Return the HTML for the Settings tab panel with skeleton loader."""
    return """
        <!-- ========== SETTINGS TAB ========== -->
        <section id="tab-settings" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="settings"></i></span> Settings</h2>
            </div>
            <div id="settings-diagnostics"></div>
            <div id="settings-content">
                <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
            </div>
        </section>"""
