"""Overview tab section: HTML skeleton for loadOverview()."""


def render_overview_tab() -> str:
    """Return the overview tab HTML section with skeleton loaders and block modal."""
    return """        <!-- ========== OVERVIEW TAB ========== -->
        <section id="tab-overview" class="tab-panel active" role="tabpanel">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="layout-dashboard"></i></span> Overview</h2>
            </div>
            <div id="overview-portrait" style="margin-bottom:16px; display:none;"></div>
            <div id="overview-content">
                <div class="glass p-6 mb-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                    <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:80%"></div><div class="skeleton skeleton-text" style="width:60%"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
                    <div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:90%"></div><div class="skeleton skeleton-text" style="width:75%"></div></div>
                </div>
                <div class="glass p-6 mb-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text" style="width:85%"></div></div>
                <div class="glass p-6 mb-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:70%"></div></div>
                <div class="glass p-6 mb-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:80%"></div></div>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6"><div class="glass p-6"><div class="skeleton skeleton-chart"></div></div><div class="glass p-6"><div class="skeleton skeleton-chart"></div></div></div>
            </div>
        </section>"""
