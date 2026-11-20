"""Activity tab section – session event history timeline.

Vertical timeline showing all session events (tool calls, chat messages,
LLM responses, session lifecycle) across platforms in chronological order.

API consumed:
    GET /api/session-events/{persona}?limit=50&offset=0&event_type=&order=desc
"""


def render_activity_tab() -> str:
    """Return the HTML for the Activity tab panel."""
    return r"""
        <section id="tab-activity" class="tab-panel" role="tabpanel">
            <div class="tab-head">
                <h2>
                    <span><i data-lucide="activity"></i></span> Activity
                </h2>
            </div>
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
                        <option value="place.moved">Place Moves</option>
                    </select>
                </label>
                <label>Order
                    <select id="act-filter-order">
                        <option value="desc">Newest first</option>
                        <option value="asc">Oldest first</option>
                    </select>
                </label>
                <button id="act-btn-refresh" data-action="act-refresh" style="margin-left:auto;">
                    <i data-lucide="refresh-cw"></i> Refresh
                </button>
            </div>
            <!-- Metrics strip (kanban #10) -->
            <div id="act-metrics" style="display:flex; gap:16px; flex-wrap:wrap; font-size:0.78rem; padding:8px 0; color:var(--text-secondary);"></div>
            <!-- Feed container -->
            <div id="act-feed"></div>
            <!-- Load more button (inserted dynamically) -->
        </section>
        """
