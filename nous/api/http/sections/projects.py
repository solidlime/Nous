"""Projects tab section: project-scoped context view (kanban #8).

1 画面で ``project:<slug>`` の記憶・決定事項・未解決の問い・wiki・タイムラインを
見る。集計はサーバ側（``GET /api/project/{persona}/{slug}/context``）で済ませ、
ここは slug 入力欄と描画箱だけ。挙動は ``static/features/projects.js``。
"""


def render_project_tab() -> str:
    """Return the projects tab HTML section."""
    return """        <!-- ========== PROJECTS TAB ========== -->
        <section id="tab-projects" class="tab-panel" role="tabpanel">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="folder-kanban"></i></span> Projects</h2>
            </div>
            <div class="glass p-4 mb-4" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                <label for="project-slug-input" style="font-size:0.8rem; color:var(--text-muted);">project slug</label>
                <input id="project-slug-input" class="input" type="text" placeholder="nous" autocomplete="off" style="max-width:240px;">
                <button id="project-load-btn" class="btn btn-primary" type="button">Load</button>
                <span id="project-status" style="font-size:0.78rem; color:var(--text-muted);"></span>
            </div>
            <div id="project-content"><div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:70%"></div><div class="skeleton skeleton-text" style="width:55%"></div></div></div>
        </section>"""
