"""Activity tab section – session event history timeline.

Vertical timeline showing all session events (tool calls, chat messages,
LLM responses, session lifecycle) across platforms in chronological order.

API consumed:
    GET /api/session-events/{persona}?limit=50&offset=0&event_type=&order=desc
"""

from pathlib import Path

_JS = (Path(__file__).resolve().parent.parent / "static/features/activity.js").read_text(encoding="utf-8")


def render_activity_tab() -> str:
    """Return the HTML for the Activity tab panel."""
    return r"""
        <section id="tab-activity" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;">
                    <span style="font-size:1.4rem;"><i data-lucide="activity"></i></span> Activity
                </h2>
            </div>
            <style>
                /* Filter toolbar */
                #act-toolbar {
                    display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end;
                    margin-bottom:16px; padding:10px 14px;
                    background:rgba(255,255,255,0.03); border:1px solid var(--glass-border);
                    border-radius:10px;
                }
                #act-toolbar label {
                    font-size:0.72rem; color:var(--text-muted);
                    display:flex; flex-direction:column; gap:3px;
                }
                #act-toolbar select, #act-toolbar button {
                    background:rgba(255,255,255,0.05); border:1px solid var(--glass-border);
                    border-radius:6px; padding:4px 10px; color:var(--text-primary);
                    font-size:0.75rem; font-family:inherit; cursor:pointer; outline:none;
                }
                #act-toolbar select:focus, #act-toolbar button:focus {
                    border-color:var(--accent-purple);
                }
                #act-toolbar button.act-filter-active {
                    background:var(--accent-purple); color:#fff; border-color:var(--accent-purple);
                }
                /* Event type color coding */
                .act-event { --act-color: var(--accent-blue); }
                .act-event.type-tool\.called { --act-color: var(--accent-blue); }
                .act-event.type-chat\.message { --act-color: var(--accent-green); }
                .act-event.type-chat\.llm_response { --act-color: var(--accent-purple); }
                .act-event.type-session\.started { --act-color: var(--accent-yellow); }
                .act-event.type-session\.compact { --act-color: var(--accent-orange); }
                .act-event.type-events\.ingested { --act-color: var(--text-muted); }
                /* Session card */
                .act-session {
                    border:1px solid var(--glass-border); border-radius:10px;
                    margin-bottom:10px; overflow:hidden;
                    background:rgba(255,255,255,0.02);
                }
                .act-session-header {
                    display:flex; align-items:center; gap:10px;
                    padding:10px 14px; cursor:pointer;
                    background:rgba(255,255,255,0.04);
                    transition:background 0.15s;
                }
                .act-session-header:hover { background:rgba(255,255,255,0.07); }
                .act-session-header .act-session-id {
                    font-family:monospace; font-size:0.8rem; color:var(--accent-purple);
                    flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
                }
                .act-session-header .act-session-meta {
                    font-size:0.72rem; color:var(--text-muted);
                    display:flex; align-items:center; gap:8px;
                }
                .act-session-header .act-chevron {
                    transition:transform 0.2s; font-size:0.8rem; color:var(--text-muted);
                }
                .act-session.open .act-chevron { transform:rotate(90deg); }
                .act-session-body {
                    display:none; padding:6px 0;
                }
                .act-session.open .act-session-body { display:block; }
                /* Individual event row */
                .act-event {
                    display:flex; align-items:flex-start; gap:10px;
                    padding:8px 14px 8px 10px; border-left:3px solid var(--act-color);
                    margin-left:10px; transition:background 0.12s;
                }
                .act-event:hover { background:rgba(255,255,255,0.03); }
                .act-event .act-event-icon {
                    font-size:0.9rem; width:20px; text-align:center; flex-shrink:0;
                    margin-top:1px;
                }
                .act-event .act-event-body { flex:1; min-width:0; }
                .act-event .act-event-summary {
                    font-size:0.8rem; color:var(--text-primary);
                    word-break:break-word;
                }
                .act-event .act-event-time {
                    font-size:0.68rem; color:var(--text-muted);
                    margin-top:2px;
                }
                .act-event .act-event-detail {
                    display:none; margin-top:6px; padding:8px 10px;
                    background:rgba(255,255,255,0.03); border-radius:6px;
                    font-size:0.75rem; color:var(--text-secondary);
                    white-space:pre-wrap; word-break:break-word;
                    max-height:200px; overflow-y:auto;
                }
                .act-event.expanded .act-event-detail { display:block; }
                .act-event .act-event-summary { cursor:pointer; }
                /* Platform badge */
                .act-platform-badge {
                    display:inline-flex; align-items:center; gap:3px;
                    font-size:0.65rem; padding:1px 6px; border-radius:4px;
                    background:rgba(255,255,255,0.08);
                }
                /* Empty state */
                .act-empty {
                    text-align:center; padding:40px 20px; color:var(--text-muted);
                }
                .act-empty i { font-size:2.5rem; margin-bottom:12px; display:block; opacity:0.4; }
                /* Load more */
                .act-load-more {
                    display:block; width:100%; padding:10px; margin-top:8px;
                    background:rgba(255,255,255,0.04); border:1px solid var(--glass-border);
                    border-radius:8px; color:var(--text-secondary); font-size:0.8rem;
                    cursor:pointer; text-align:center; transition:background 0.15s;
                }
                .act-load-more:hover { background:rgba(255,255,255,0.08); }
            </style>
            <!-- Toolbar -->
            <div id="act-toolbar">
                <label>Event type
                    <select id="act-filter-type">
                        <option value="">All</option>
                        <option value="tool.called">Tool Calls</option>
                        <option value="chat.message">Chat Messages</option>
                        <option value="chat.llm_response">LLM Responses</option>
                        <option value="session.started">Session Starts</option>
                        <option value="session.compact">Compressions</option>
                        <option value="events.ingested">External Events</option>
                    </select>
                </label>
                <label>Order
                    <select id="act-filter-order">
                        <option value="desc">Newest first</option>
                        <option value="asc">Oldest first</option>
                    </select>
                </label>
                <button id="act-btn-refresh" onclick="loadActivity(true)" style="margin-left:auto;">
                    <i data-lucide="refresh-cw"></i> Refresh
                </button>
            </div>
            <!-- Feed container -->
            <div id="act-feed"></div>
            <!-- Load more button (inserted dynamically) -->
        </section>
        """


def render_activity_js() -> str:
    """Return the JavaScript for the Activity tab."""
    return _JS
