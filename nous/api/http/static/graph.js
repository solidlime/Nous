
;(function() {
var S = window.S;
var { esc, api, truncate } = window.Nous.Core;

/* ================================================================
 *  Knowledge Graph — vis-network interactive memory visualization
 * ================================================================ */

let graphNetwork = null;
let graphData = null;
let graphNodeLimit = 100;

/* ---- Helpers ---- */

function _graphFontColor() {
    return document.documentElement.classList.contains('light') ? '#1e1b4b' : '#f1f5f9';
}
function _graphEdgeColor(isRelated) {
    var isLight = document.documentElement.classList.contains('light');
    if (isRelated) {
        return {
            color:     isLight ? 'rgba(109,40,217,0.75)' : 'rgba(167,139,250,0.85)',
            highlight: isLight ? '#7c3aed' : '#c4b5fd',
            hover:     isLight ? '#7c3aed' : '#c4b5fd'
        };
    }
    return {
        color:     isLight ? 'rgba(100,116,139,0.55)' : 'rgba(148,163,184,0.65)',
        highlight: isLight ? '#475569' : '#94a3b8',
        hover:     isLight ? '#475569' : '#94a3b8'
    };
}

/* ---- Main loader ---- */

async function loadGraph() {
    var el = document.getElementById('graph-content');
    var container = document.getElementById('graph-container');
    var loading = document.getElementById('graph-loading');
    var statsEl = document.getElementById('graph-stats');

    if (loading) loading.style.display = 'flex';

    try {
        var data = await api(
            '/api/graph/' + encodeURIComponent(S.persona) + '?limit=' + graphNodeLimit
        );
        graphData = data;

        populateGraphFilters(data.nodes);

        var built = buildVisData(data.nodes, data.edges);
        var filtered = applyGraphFilters(built.visNodes, built.visEdges);

        renderNetwork(container, filtered.nodes, filtered.edges);

        if (statsEl) {
            statsEl.textContent = filtered.nodes.length + ' nodes · ' + filtered.edges.length + ' edges';
        }

    } catch (e) {
        if (container) container.innerHTML = errorCard('Failed to load graph: ' + e.message);
    } finally {
        var l = document.getElementById('graph-loading');
        if (l) l.style.display = 'none';
        if (loading) loading.style.display = 'none';
    }
}
window.loadGraph = loadGraph;

/* ---- Populate filter dropdowns ---- */

function populateGraphFilters(nodes) {
    var tagSet = new Set();
    var emotionSet = new Set();
    nodes.forEach(function(n) {
        (n.tags || []).forEach(function(t) { tagSet.add(t); });
        if (n.emotion) emotionSet.add(n.emotion);
    });

    var tagFilter = document.getElementById('graph-tag-filter');
    var emotionFilter = document.getElementById('graph-emotion-filter');
    if (!tagFilter || !emotionFilter) return;
    var currentTags = Array.from(tagFilter.selectedOptions).map(function(o) { return o.value; }).filter(Boolean);
    tagFilter.innerHTML = '<option value="">All Tags</option>' +
        Array.from(tagSet).sort().map(function(t) {
            return '<option value="' + esc(t) + '"' +
                   (currentTags.includes(t) ? ' selected' : '') + '>' + esc(t) + '</option>';
        }).join('');

    var currentEmo = emotionFilter.value;
    emotionFilter.innerHTML = '<option value="">All Emotions</option>' +
        Array.from(emotionSet).sort().map(function(e) {
            return '<option value="' + esc(e) + '"' +
                   (currentEmo === e ? ' selected' : '') + '>' + esc(e) + '</option>';
        }).join('');
}

/* ---- Build vis-network DataSet arrays ---- */

function buildVisData(nodes, edges) {
    var fontColor = _graphFontColor();

    var visNodes = nodes.map(function(n) {
        var emoColor = window.EMOTION_COLORS[n.emotion] || '#94a3b8';
        var sz = 10 + (n.importance || 0.5) * 30;
        var nodeLabel = truncate(n.content, 20) || n.key || 'Unknown';
        return {
            id: n.key,
            label: nodeLabel,
            title: buildTooltip(n),
            size: sz,
            color: {
                background: emoColor,
                border: emoColor,
                highlight: { background: emoColor, border: '#fff' },
                hover:     { background: emoColor, border: '#fff' }
            },
            font: { color: fontColor, size: 11, face: 'system-ui' },
            borderWidth: 2,
            shadow: { enabled: true, color: emoColor, size: 8, x: 0, y: 0 },
            _data: n
        };
    });

    var visEdges = edges.map(function(e, i) {
        var isRelated = (e.type === 'related');
        return {
            id: 'e' + i,
            from: e.source,
            to: e.target,
            dashes: !isRelated,
            width: isRelated ? 2.5 : 1.5,
            color: _graphEdgeColor(isRelated),
            smooth: { type: 'continuous' },
            _type: e.type,
            _tag:  e.tag || '',
            _from: e.source,
            _to:   e.target
        };
    });

    return { visNodes: visNodes, visEdges: visEdges };
}

/* ---- Tooltip HTML ---- */

function buildTooltip(n) {
    var el = document.createElement('div');
    el.style.cssText = 'background:#1e293b;color:#e2e8f0;border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.6;max-width:300px;white-space:normal;word-break:break-word;box-shadow:0 4px 16px rgba(0,0,0,0.5);';
    var h = '<div style="margin-bottom:6px;font-weight:600;color:#f8fafc">' + esc(truncate(n.content, 120)) + '</div>';
    if (n.tags && n.tags.length) {
        h += '<div style="margin-bottom:4px;color:#94a3b8">&#127991; ' + n.tags.map(function(t) { return esc(t); }).join(', ') + '</div>';
    }
    if (n.emotion) {
        h += '<div style="margin-bottom:4px;color:#94a3b8">&#128173; ' + esc(n.emotion) + '</div>';
    }
    h += '<div style="color:#94a3b8">&#11088; Importance: ' + ((n.importance || 0) * 100).toFixed(0) + '%</div>';
    el.innerHTML = h;
    return el;
}

/* ---- Client-side filtering ---- */

function applyGraphFilters(visNodes, visEdges) {
    var tagFilter     = document.getElementById('graph-tag-filter');
    var emotionFilter = document.getElementById('graph-emotion-filter');
    var selectedTags  = Array.from(tagFilter.selectedOptions).map(function(o) { return o.value; }).filter(Boolean);
    var selectedEmo   = emotionFilter.value;

    var filtered = visNodes;

    if (selectedTags.length > 0) {
        filtered = filtered.filter(function(n) {
            var tags = n._data.tags || [];
            return selectedTags.some(function(t) { return tags.includes(t); });
        });
    }
    if (selectedEmo) {
        filtered = filtered.filter(function(n) { return n._data.emotion === selectedEmo; });
    }

    var visibleIds = new Set(filtered.map(function(n) { return n.id; }));
    var filteredEdges = visEdges.filter(function(e) {
        return visibleIds.has(e._from) && visibleIds.has(e._to);
    });

    return { nodes: filtered, edges: filteredEdges };
}

/* ---- Render / re-render vis.Network ---- */

function renderNetwork(container, nodes, edges) {
    if (typeof vis === 'undefined') {
        container.innerHTML = errorCard('vis-network library not available. Please check internet connectivity.');
        return;
    }
    var loading = document.getElementById('graph-loading');

    /* Empty state */
    if (nodes.length === 0) {
        if (graphNetwork) { graphNetwork.destroy(); graphNetwork = null; }
        if (loading) loading.style.display = 'none';
        container.innerHTML =
            '<div class="empty-state">' +
            '<div class="empty-state-icon"><i data-lucide="share-2"></i></div>' +
            '<div class="empty-state-text">まだグラフに表示できる記憶がありません。<br>記憶を作成するとここに表示されます。</div>' +
            '<button class="empty-state-cta" onclick="switchTab(\'memories\')"><i data-lucide="brain"></i> 記憶を作成</button>' +
            '</div>';
        return;
    }

    var dataSet = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges)
    };

    var physicsEnabled = document.getElementById('graph-physics-toggle').checked;

    var options = {
        physics: {
            enabled: physicsEnabled,
            barnesHut: {
                gravitationalConstant: -3000,
                centralGravity: 0.3,
                springLength: 120,
                springConstant: 0.04,
                damping: 0.09
            },
            stabilization: { iterations: 150, fit: true }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            hideEdgesOnDrag: true,
            hideEdgesOnZoom: true,
            multiselect: false
        },
        nodes: {
            shape: 'dot',
            scaling: { min: 10, max: 40 },
            font: { color: _graphFontColor(), size: 11 }
        },
        edges: {
            smooth: { type: 'continuous', roundness: 0.2 }
        },
        layout: {
            improvedLayout: (nodes.length < 150)
        }
    };

    if (graphNetwork) { graphNetwork.destroy(); }

    graphNetwork = new vis.Network(container, dataSet, options);

    /* Click → open side panel */
    graphNetwork.on('click', function(params) {
        if (params.nodes.length > 0) {
            var nodeId = params.nodes[0];
            var node = dataSet.nodes.get(nodeId);
            if (node && node._data) {
                openGraphDetailPanel(node._data);
            }
        } else {
            closeGraphDetailPanel();
        }
    });

    /* Double-click → open full modal via openMemModal */
    graphNetwork.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            var nodeId = params.nodes[0];
            var node = dataSet.nodes.get(nodeId);
            if (node && node._data) {
                var d = node._data;
                openMemModal({
                    memory_key:  d.key,
                    content:     d.content,
                    tags:        d.tags,
                    emotion: d.emotion,
                    importance:  d.importance
                });
            }
        }
    });

    /* Stabilization done → stop physics jitter */
    graphNetwork.once('stabilizationIterationsDone', function() {
        graphNetwork.setOptions({ physics: { stabilization: { enabled: false } } });
    });
}

/* ---- Detail side panel ---- */

function openGraphDetailPanel(data) {
    var panel   = document.getElementById('graph-detail-panel');
    var overlay = document.getElementById('graph-panel-overlay');
    var body    = document.getElementById('graph-panel-body');

    var tags = (data.tags || []).map(function(t) {
        return '<span class="badge badge-purple">' + esc(t) + '</span>';
    }).join(' ');

    var emoColor = window.EMOTION_COLORS[data.emotion] || '#94a3b8';

    var html = '';
    /* Key */
    html += '<div style="margin-bottom:16px">';
    html += '  <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">Key</div>';
    html += '  <div style="font-family:monospace;font-size:0.8rem;color:var(--accent-purple);word-break:break-all">' + esc(data.key) + '</div>';
    html += '</div>';

    /* Content */
    html += '<div style="margin-bottom:16px">';
    html += '  <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">Content</div>';
    html += '  <div style="color:var(--text-primary);line-height:1.6;white-space:pre-wrap">' + esc(data.content) + '</div>';
    html += '</div>';

    /* Tags */
    if (tags) {
        html += '<div style="margin-bottom:16px">';
        html += '  <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:6px">Tags</div>';
        html += '  <div style="display:flex;flex-wrap:wrap;gap:4px">' + tags + '</div>';
        html += '</div>';
    }

    /* Emotion */
    if (data.emotion) {
        html += '<div style="margin-bottom:16px">';
        html += '  <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">Emotion</div>';
        html += '  <div style="display:flex;align-items:center;gap:6px">';
        html += '    <span style="width:10px;height:10px;border-radius:50%;background:' + emoColor + ';display:inline-block"></span>';
        html += '    <span style="color:var(--text-secondary)">' + esc(data.emotion) + '</span>';
        html += '  </div>';
        html += '</div>';
    }

    /* Emotion bar */
    if (data.emotion) {
        html += '<div style="margin-bottom:16px">';
        html += renderEmotionBars(data.emotion, data.emotion_intensity);
        html += '</div>';
    }

    /* Body state bars */
    if (data.body_state && Object.keys(data.body_state).length > 0) {
        html += '<div style="margin-bottom:16px">';
        html += renderBodyStateBars(data.body_state);
        html += '</div>';
    }

    /* Importance bar */
    if (data.importance != null) {
        var pct = (data.importance * 100).toFixed(0);
        html += '<div style="margin-bottom:16px">';
        html += '  <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">Importance</div>';
        html += '  <div style="display:flex;align-items:center;gap:8px">';
        html += '    <div style="flex:1;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">';
        html += '      <div style="width:' + pct + '%;height:100%;background:var(--accent-yellow);border-radius:3px"></div>';
        html += '    </div>';
        html += '    <span style="color:var(--accent-yellow);font-size:0.85rem">' + pct + '%</span>';
        html += '  </div>';
        html += '</div>';
    }

    body.innerHTML = html;
    panel.style.right = '0';
    overlay.style.display = 'block';
}

function closeGraphDetailPanel() {
    var panel   = document.getElementById('graph-detail-panel');
    var overlay = document.getElementById('graph-panel-overlay');
    if (panel)   panel.style.right = '-400px';
    if (overlay) overlay.style.display = 'none';
}

/* ---- Helper: re-apply filters without refetch ---- */

function _graphRefilter() {
    if (!graphData) return;
    var built    = buildVisData(graphData.nodes, graphData.edges);
    var filtered = applyGraphFilters(built.visNodes, built.visEdges);
    renderNetwork(document.getElementById('graph-container'), filtered.nodes, filtered.edges);
    var statsEl = document.getElementById('graph-stats');
    if (statsEl) {
        statsEl.textContent = filtered.nodes.length + ' nodes \· ' + filtered.edges.length + ' edges';
    }
}

/* ---- Event wiring (runs once at parse time) ---- */

(function setupGraphEvents() {
    /* Limit buttons */
    document.querySelectorAll('.graph-limit-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.graph-limit-btn').forEach(function(b) {
                b.classList.remove('active');
            });
            this.classList.add('active');
            graphNodeLimit = parseInt(this.dataset.limit, 10);
            loadGraph();
        });
    });

    /* Tag filter → re-apply (no refetch) */
    var tagFilter = document.getElementById('graph-tag-filter');
    if (tagFilter) tagFilter.addEventListener('change', _graphRefilter);

    /* Emotion filter → re-apply (no refetch) */
    var emotionFilter = document.getElementById('graph-emotion-filter');
    if (emotionFilter) emotionFilter.addEventListener('change', _graphRefilter);

    /* Physics toggle */
    var physToggle = document.getElementById('graph-physics-toggle');
    if (physToggle) physToggle.addEventListener('change', function() {
        if (graphNetwork) {
            graphNetwork.setOptions({ physics: { enabled: this.checked } });
        }
    });

    /* Refresh button */
    var refreshBtn = document.getElementById('graph-refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadGraph);

    /* Close panel */
    var panelClose = document.getElementById('graph-panel-close');
    if (panelClose) panelClose.addEventListener('click', closeGraphDetailPanel);
    var panelOverlay = document.getElementById('graph-panel-overlay');
    if (panelOverlay) panelOverlay.addEventListener('click', closeGraphDetailPanel);

    /* ESC key closes panel */
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var panel = document.getElementById('graph-detail-panel');
            if (panel && panel.style.right === '0px') {
                closeGraphDetailPanel();
            }
        }
    });
})();
})();
