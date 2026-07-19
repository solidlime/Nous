"""Knowledge Graph tab section for the Nous Dashboard.

Interactive visualization of memory relationships using vis-network.
Provides a force-directed graph where nodes represent memories and
edges represent semantic/tag-based relationships. Supports filtering
by tag and emotion, adjustable node limits, physics toggle, and a
slide-out detail panel for inspecting individual memories.

API consumed:
    GET /api/graph/{persona}?limit={limit}

Response shape:
    {
        "persona": "xxx",
        "nodes": [{ "key", "content", "tags", "emotion", "importance" }],
        "edges": [{ "source", "target", "type", "tag?" }],
        "node_count": int,
        "edge_count": int
    }
"""

from pathlib import Path

_JS = (Path(__file__).resolve().parent.parent / "static/graph.js").read_text(encoding="utf-8")


def render_graph_tab() -> str:
    """Return the HTML for the Knowledge Graph tab panel.

    Includes:
    - Toolbar with tag/emotion filters, node-limit buttons, physics toggle, refresh
    - vis-network container (600px height)
    - Slide-out detail panel (right side, 400px)
    - Scoped styles for spinner, active limit button, and panel overlay
    """
    return """
        <!-- ========== KNOWLEDGE GRAPH TAB ========== -->
        <section id="tab-graph" class="tab-panel" role="tabpanel">
            <div style="margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--glass-border);">
                <h2 style="font-size:1.25rem; font-weight:700; color:var(--text-primary); display:flex; align-items:center; gap:10px;"><span style="font-size:1.4rem;"><i data-lucide="share-2"></i></span> Knowledge Graph</h2>
            </div>
          <style>
            /* Spinner animation for graph loading */
            @keyframes graph-spin {
              to { transform: rotate(360deg); }
            }
            .graph-spinner {
              width: 36px; height: 36px;
              border: 3px solid rgba(var(--accent-blue-rgb), 0.2);
              border-top-color: var(--accent-blue);
              border-radius: 50%;
              animation: graph-spin 0.8s linear infinite;
            }

            /* Active state for node-limit buttons */
            .graph-limit-btn.active {
              background: rgba(var(--accent-blue-rgb), 0.35);
              border-color: var(--accent-blue);
              box-shadow: 0 0 12px rgba(var(--accent-blue-rgb), 0.15);
            }

            /* Detail panel backdrop - respects light/dark via variable */
            #graph-panel-overlay {
              backdrop-filter: blur(2px);
            }

            /* Multi-select tweak: show scrollbar when expanded */
            #graph-tag-filter {
              scrollbar-width: thin;
            }
            #graph-tag-filter:focus {
              max-height: 160px !important;
            }

            /* Make vis-network canvas fill container */
            #graph-container .vis-network {
              outline: none;
            }

            /* Override vis-network default tooltip style */
            #graph-container .vis-tooltip {
              white-space: normal !important;
              background: transparent !important;
              border: none !important;
              padding: 0 !important;
              box-shadow: none !important;
            }
          </style>

          <div id="graph-content">
            <!-- Toolbar -->
            <div class="glass" style="padding:16px;margin-bottom:16px">
              <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <!-- Tag filter: multi-select -->
                <select id="graph-tag-filter" class="glass-input" multiple
                        style="min-width:150px;max-height:36px"
                        title="Filter by tags (hold Ctrl/Cmd to select multiple)">
                  <option value="">All Tags</option>
                </select>

                <!-- Emotion filter -->
                <select id="graph-emotion-filter" class="glass-input"
                        style="min-width:140px">
                  <option value="">All Emotions</option>
                </select>

                <!-- Node limit buttons -->
                <div style="display:flex;gap:4px">
                  <button class="glass-btn graph-limit-btn" data-limit="50"
                          style="padding:6px 14px;font-size:0.82rem">50</button>
                  <button class="glass-btn graph-limit-btn active" data-limit="100"
                          style="padding:6px 14px;font-size:0.82rem">100</button>
                  <button class="glass-btn graph-limit-btn" data-limit="200"
                          style="padding:6px 14px;font-size:0.82rem">200</button>
                </div>

                <!-- Physics toggle -->
                <label style="display:flex;align-items:center;gap:6px;color:var(--text-secondary);font-size:0.85rem;cursor:pointer;user-select:none">
                  <input type="checkbox" id="graph-physics-toggle" checked
                         style="accent-color:var(--accent-purple)"> Physics
                </label>

                <!-- Refresh -->
                <button id="graph-refresh-btn" class="glass-btn"
                        title="Refresh graph"
                        style="padding:6px 14px;font-size:0.82rem"><i data-lucide="refresh-cw"></i> Refresh</button>

                <!-- Stats (pushed to right) -->
                <span id="graph-stats"
                      style="color:var(--text-muted);font-size:0.8rem;margin-left:auto"></span>
              </div>
            </div>

            <!-- Graph container -->
            <div id="graph-container" class="glass"
                 style="height:600px;position:relative;overflow:hidden">
              <!-- vis-network renders here -->
              <div id="graph-loading"
                   style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;z-index:10">
                <div style="text-align:center">
                  <div class="graph-spinner" style="margin:0 auto 12px"></div>
                  <span style="color:var(--text-muted)">Loading graph...</span>
                </div>
              </div>
            </div>

            <!-- Detail side panel -->
            <div id="graph-detail-panel"
                 style="position:fixed;top:0;right:-400px;width:400px;max-width:90vw;height:100vh;z-index:1000;transition:right 0.3s ease;overflow-y:auto">
              <div style="background:var(--bg-primary);border-left:1px solid var(--glass-border);height:100%;padding:24px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                  <h3 style="font-size:1.1rem;font-weight:600;color:var(--text-primary)">Memory Details</h3>
                  <button id="graph-panel-close" class="glass-btn"
                          style="padding:4px 10px;font-size:0.9rem"><i data-lucide="x"></i></button>
                </div>
                <div id="graph-panel-body"></div>
              </div>
            </div>
            <div id="graph-panel-overlay"
                 style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.3);z-index:999"></div>
          </div>
        </section>"""


def render_graph_js() -> str:
    """Return the JavaScript for the Knowledge Graph tab.

    Defines:
    - ``loadGraph()``              — main entry; fetches data, builds graph
    - ``populateGraphFilters()``   — populates tag/emotion <select> from node data
    - ``buildVisData()``           — converts API nodes/edges → vis-network format
    - ``buildTooltip()``           — HTML tooltip for node hover
    - ``applyGraphFilters()``      — client-side tag/emotion filtering
    - ``renderNetwork()``          — creates / re-creates vis.Network instance
    - ``openGraphDetailPanel()``   — shows slide-out detail panel for a node
    - ``closeGraphDetailPanel()``  — hides the detail panel
    - IIFE ``setupGraphEvents()``  — wires toolbar event listeners

    No ``<script>`` tags — the string is concatenated by ``dashboard.py``.
    """
    return _JS
