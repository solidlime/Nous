"""Projects tab section: project-scoped context view (kanban #8).

1 画面で ``project:<slug>`` の記憶・決定事項・未解決の問い・wiki・タイムラインを
見る。集計はサーバ側（``GET /api/project/{persona}/{slug}/context``）で済ませ、
ここは slug 入力欄と描画箱だけ。挙動は ``static/features/projects.js``。
"""


def render_project_tab() -> str:
    """Return the projects tab HTML section."""
    return """        <!-- ========== PROJECTS TAB ========== -->
        <section id="tab-projects" class="tab-panel" role="tabpanel">
            <div class="tab-head">
                <h2><span><i data-lucide="folder-kanban"></i></span> Projects</h2>
            </div>
            <div class="glass p-4 mb-4 proj-form">
                <label for="project-slug-input" class="proj-form-label">project slug</label>
                <input id="project-slug-input" class="glass-input proj-slug-input" type="text" placeholder="nous" autocomplete="off">
                <button id="project-load-btn" class="glass-btn" type="button">Load</button>
                <span id="project-status" class="proj-status"></span>
            </div>
            <div id="project-content"><div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:70%"></div><div class="skeleton skeleton-text" style="width:55%"></div></div></div>
        </section>"""
