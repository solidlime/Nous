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

from pathlib import Path

_JS = (Path(__file__).resolve().parent.parent / "static/features/timeline.js").read_text(encoding="utf-8")


def render_timeline_tab() -> str:
    """Return the HTML for the Memory Timeline tab panel.

    Includes:
    - Filter toolbar (emotion type, tag, importance min, date range, page size)
    - vis-timeline container (500px height)
    - Click-to-inspect detail panel (slide-out, right side)
    - Scoped styles for timeline items and panel
    """
    return r"""
        <section id="tab-timeline" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="calendar"></i></span> Timeline</h2>
            </div>
            <style>
                #tab-timeline .tl-toolbar {
                    display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end;
                    margin-bottom: 12px; padding: 10px 12px;
                    background: rgba(255,255,255,0.03); border: 1px solid var(--glass-border);
                    border-radius: 10px;
                }
                #tab-timeline .tl-toolbar label {
                    font-size: 0.72rem; color: var(--text-muted); display: flex;
                    flex-direction: column; gap: 3px;
                }
                #tab-timeline .tl-toolbar select, #tab-timeline .tl-toolbar input {
                    background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border);
                    border-radius: 6px; padding: 4px 8px; color: var(--text-primary);
                    font-size: 0.75rem; font-family: inherit; outline: none; min-width: 100px;
                }
                #tab-timeline .tl-toolbar select:focus, #tab-timeline .tl-toolbar input:focus {
                    border-color: var(--accent-purple);
                }
                #tl-container {
                    height: 500px; border: 1px solid var(--glass-border);
                    border-radius: 10px; overflow: hidden;
                    background: rgba(0,0,0,0.15);
                }
                #tl-container .vis-item {
                    border-radius: 6px; border-width: 2px; font-size: 0.72rem;
                    transition: transform 0.15s, box-shadow 0.15s;
                    overflow: hidden;
                }
                #tl-container .vis-item:hover {
                    transform: scale(1.02); z-index: 10;
                    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
                }
                #tl-container .vis-item.vis-selected {
                    border-color: var(--accent-purple) !important;
                    box-shadow: 0 0 12px rgba(var(--accent-blue-rgb), 0.4);
                }
                #tl-container .vis-item .vis-item-content {
                    padding: 4px 8px; white-space: nowrap; overflow: hidden;
                    text-overflow: ellipsis; max-width: 200px;
                }
                #tl-loading {
                    display: flex; align-items: center; justify-content: center;
                    height: 500px; color: var(--text-muted); font-size: 0.9rem;
                }
                /* Emotion legend */
                #tl-legend {
                    display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 8px;
                }
                #tl-legend .tl-legend-dot {
                    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                    margin-right: 3px; vertical-align: middle;
                }
                #tl-legend span { font-size: 0.68rem; color: var(--text-muted); }
            </style>

            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                <h2 style="font-size:1.1rem;font-weight:600;color:var(--text-primary);"><i data-lucide="clock"></i> Memory Timeline</h2>
                <button data-action="tl-reload" style="background:none;border:1px solid var(--glass-border);border-radius:6px;color:var(--text-muted);padding:4px 10px;cursor:pointer;font-size:0.75rem;"><i data-lucide="refresh-cw"></i> 更新</button>
            </div>

            <div class="tl-toolbar">
                <label>感情 <select id="tl-emotion"><option value="">すべて</option></select></label>
                <label>タグ <input type="text" id="tl-tag" placeholder="例: goal" /></label>
                <label>重要度≧ <input type="number" id="tl-min-importance" value="0" min="0" max="1" step="0.1" style="min-width:60px;" /></label>
                <label>件数 <select id="tl-per-page"><option value="50">50</option><option value="100" selected>100</option><option value="200">200</option><option value="500">500</option></select></label>
            </div>

            <div id="tl-container"><div id="tl-loading">読み込み中...</div></div>

            <div id="tl-legend"></div>
        </section>
    """


def render_timeline_js() -> str:
    """Return the JavaScript for the Memory Timeline tab."""
    return _JS
