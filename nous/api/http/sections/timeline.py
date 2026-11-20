"""Memory Timeline tab section for the Nous Dashboard.

Interactive chronological visualization of memories using vis-timeline.
Memories are displayed as colored items along a horizontal time axis,
color-coded by emotion type with importance-based sizing. Supports
filtering by emotion type, tag, importance threshold, and time range.

API consumed:
    GET /api/observations/{persona}?page={page}&per_page={per_page}

Response shape (per entry):
    {
        "key", "content", "created_at", "importance",
        "emotion_type", "emotion_intensity", "tags", ...
    }
"""


def render_timeline_tab() -> str:
    """Return the HTML for the Memory Timeline tab panel.

    Includes:
    - Filter toolbar (emotion type, tag, importance min, date range, page size)
    - vis-timeline container (500px height)
    - Click-to-inspect detail panel (slide-out, right side)
    """
    return r"""
        <section id="tab-timeline" class="tab-panel" role="tabpanel">
            <div class="tab-head">
                <h2><span><i data-lucide="calendar"></i></span> Timeline</h2>
            </div>

            <div class="tl-head">
                <h2 class="tl-subhead"><i data-lucide="clock"></i> Memory Timeline</h2>
                <button data-action="tl-reload" class="tl-reload-btn"><i data-lucide="refresh-cw"></i> 更新</button>
            </div>

            <div class="tl-toolbar">
                <label>感情 <select id="tl-emotion"><option value="">すべて</option></select></label>
                <label>タグ <input type="text" id="tl-tag" class="glass-input" placeholder="例: goal" /></label>
                <label>重要度≧ <input type="number" id="tl-min-importance" class="glass-input tl-min-imp" value="0" min="0" max="1" step="0.1" /></label>
                <label>件数 <select id="tl-per-page"><option value="50">50</option><option value="100" selected>100</option><option value="200">200</option><option value="500">500</option></select></label>
            </div>

            <div id="tl-container"><div id="tl-loading">読み込み中...</div></div>

            <div id="tl-legend"></div>
        </section>
    """
