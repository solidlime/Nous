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
            <div class="tab-head">
                <h2><span><i data-lucide="settings"></i></span> Settings</h2>
            </div>
            <div id="settings-diagnostics"></div>
            <div id="settings-content">
                <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
            </div>
        </section>"""
