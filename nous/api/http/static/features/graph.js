/* ================================================================
 *  Knowledge Graph — vis-network interactive memory visualization
 *  Namespace: N.Features.Graph.*
 *  ================================================================ */
N.Features.Graph = N.Features.Graph || {};

;(function() {
var S = window.S;
var { esc, api, truncate, safeSetHTML } = window.Nous.Core;

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
function _graphEdgeColor(type) {
    var isLight = document.documentElement.classList.contains('light');
    if (type === 'related') {
        return {
            color:     isLight ? 'rgba(0,82,204,0.75)' : 'rgba(0,122,255,0.85)',
            highlight: isLight ? '#0051d5' : '#60a5fa',
            hover:     isLight ? '#0051d5' : '#60a5fa'
        };
    }
    if (type === 'relation') {
        return {
            color:     isLight ? 'rgba(124,58,237,0.75)' : 'rgba(167,139,250,0.85)',
            highlight: isLight ? '#6d28d9' : '#c4b5fd',
            hover:     isLight ? '#6d28d9' : '#c4b5fd'
        };
    }
    return {
        color:     isLight ? 'rgba(100,116,139,0.55)' : 'rgba(148,163,184,0.65)',
        highlight: isLight ? '#475569' : '#94a3b8',
        hover:     isLight ? '#475569' : '#94a3b8'
    };
}

/* ---- Wiring flash (brain simulation visualization) ---- */

/* Kind → flash color. novelty_gate is the biggest pulse (gold);
   replay_fire blue-purple; recall_boost keeps the existing emphasis. */
var FLASH_COLORS = {
    novelty_gate: '#ffd60a',
    replay_fire: '#7c7cf0',
    recall_boost: '#30d158',
    link_fire: '#bf5af2',
    ppr_hit: '#007aff'
};
var FLASH_RESTORE_MS = 500;
var FLASH_PULSE = { novelty_gate: 2.0, default: 1.6 };
var flashTimers = {}; // per-node generation token: exactly one timer per node
var flashBases = {};  // original node data captured at rest — restore source
var graphDataSet = null;
var flashSSE = null;

/* renderNetwork hands its fresh DataSet over (also the test hook). */
function setGraphFlashDataSet(ds) {
    Object.keys(flashTimers).forEach(function (id) { clearTimeout(flashTimers[id]); });
    flashTimers = {};
    flashBases = {};
    graphDataSet = ds;
}

/* Flash one node: newest flash wins, restore is a diff update against
   the original node data (captured when the node was at rest — a flash
   mid-pulse must not corrupt the base). buildVisData keeps the pristine
   originals in _data; setGraphFlashDataSet resets everything on re-render. */
function flashNodeOn(nodes, id, kind) {
    var color = FLASH_COLORS[kind];
    if (!nodes || !color) return false;
    var node = nodes.get(id);
    if (!node) return false;
    if (flashTimers[id]) clearTimeout(flashTimers[id]); // old generation loses
    var base = flashBases[id] || { size: node.size || 10, color: node.color };
    flashBases[id] = base;
    var pulse = FLASH_PULSE[kind] || FLASH_PULSE.default;
    nodes.update({
        id: id,
        color: {
            background: color,
            border: color,
            highlight: base.color.highlight,
            hover: base.color.hover
        },
        size: base.size * pulse
    });
    flashTimers[id] = setTimeout(function () {
        delete flashTimers[id];
        delete flashBases[id];
        nodes.update({ id: id, color: base.color, size: base.size });
    }, FLASH_RESTORE_MS);
    return true;
}

function handleWiringEvent(ev) {
    if (S.tab !== 'graph') return false; // graph view only
    var nodes = graphDataSet && graphDataSet.nodes;
    if (!nodes) return false;
    var flashed = false;
    if (ev.source) flashed = flashNodeOn(nodes, ev.source, ev.kind) || flashed;
    if (ev.target) flashed = flashNodeOn(nodes, ev.target, ev.kind) || flashed;
    return flashed;
}

function connectGraphFlash() {
    if (flashSSE) return flashSSE; // single-flight
    // EventSource cannot send X-Persona headers — pass persona via query param
    // (same channel as the chat wiring feed; server resolves it in deps.py).
    flashSSE = new EventSource('/api/memory/wiring/stream' +
        (S.persona ? '?persona=' + encodeURIComponent(S.persona) : ''));
    flashSSE.addEventListener('wiring', function (e) {
        var ev;
        try { ev = JSON.parse(e.data); } catch (err) { return; }
        handleWiringEvent(ev);
    });
    return flashSSE;
}

function disconnectGraphFlash() {
    if (flashSSE) { flashSSE.close(); flashSSE = null; }
}

function setFlashEnabled(enabled) {
    if (enabled) connectGraphFlash();
    else disconnectGraphFlash();
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

        /* Flash subscription follows the brain setting (graph view is live here) */
        api('/api/chat/' + encodeURIComponent(S.persona) + '/config')
            .then(function (cfg) { setFlashEnabled(cfg.brain_graph_flash_enabled !== false); })
            .catch(function () { /* config unavailable → no subscription */ });

    } catch (e) {
        console.error('graph load failed:', e);
        if (el) safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load graph data', function(){ loadGraph(); }));
    } finally {
        var l = document.getElementById('graph-loading');
        if (l) l.style.display = 'none';
        if (loading) loading.style.display = 'none';
    }
}
/* N.Features. KnowledgeGraph.loadGraph registered below */

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
    safeSetHTML(tagFilter, '<option value=""' + (currentTags.length ? '' : ' selected') + '>All Tags</option>' +
        Array.from(tagSet).sort().map(function(t) {
            return '<option value="' + esc(t) + '"' +
                   (currentTags.includes(t) ? ' selected' : '') + '>' + esc(t) + '</option>';
        }).join(''));

    var currentEmo = emotionFilter.value;
    safeSetHTML(emotionFilter, '<option value="">All Emotions</option>' +
        Array.from(emotionSet).sort().map(function(e) {
            return '<option value="' + esc(e) + '"' +
                   (currentEmo === e ? ' selected' : '') + '>' + esc(e) + '</option>';
        }).join(''));
}

/* ---- Build vis-network DataSet arrays ---- */

function buildVisData(nodes, edges) {
    var fontColor = _graphFontColor();

    var visNodes = nodes.map(function(n) {
        /* Entity node: fixed-color dot sized by mention count */
        if (n.kind === 'entity') {
            var entColor = '#a78bfa';
            return {
                id: n.key,
                label: truncate(n.label, 20) || n.key,
                title: buildEntityTooltip(n),
                shape: 'dot',
                size: 8 + Math.min(n.mention_count || 1, 10) * 2,
                color: {
                    background: entColor,
                    border: entColor,
                    highlight: { background: entColor, border: '#fff' },
                    hover:     { background: entColor, border: '#fff' }
                },
                font: { color: fontColor, size: 11, face: 'system-ui' },
                borderWidth: 2,
                shadow: { enabled: true, color: entColor, size: 8, x: 0, y: 0 },
                _data: n
            };
        }
        var emoColor = N.Core.EMOTION_COLORS[n.emotion] || '#94a3b8';
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
        var isRelated  = (e.type === 'related');
        var isMentions = (e.type === 'mentions');
        var isRelation = (e.type === 'relation');
        return {
            id: 'e' + i,
            from: e.source,
            to: e.target,
            dashes: isMentions ? [2, 4] : !isRelated,
            width: isRelated ? 2.5 : (isRelation ? 2 : 1),
            color: _graphEdgeColor(e.type),
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

function buildEntityTooltip(n) {
    var el = document.createElement('div');
    el.style.cssText = 'background:#1e293b;color:#e2e8f0;border-radius:8px;padding:10px 12px;font-size:12px;line-height:1.6;max-width:300px;white-space:normal;word-break:break-word;box-shadow:0 4px 16px rgba(0,0,0,0.5);';
    var h = '<div style="margin-bottom:4px;font-weight:600;color:#f8fafc">' + esc(n.label || n.key) + '</div>';
    h += '<div style="color:#94a3b8">&#127991; ' + esc(n.entity_type || 'entity') + ' &#183; mentions: ' + (n.mention_count || 0) + '</div>';
    safeSetHTML(el, h);
    return el;
}

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
    safeSetHTML(el, h);
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
        safeSetHTML(container, N.Components.skeleton.errorCard('vis-network library not available. Please check internet connectivity.', function(){ loadGraph(); }));
        return;
    }
    var loading = document.getElementById('graph-loading');

    /* Empty state */
    if (nodes.length === 0) {
        if (graphNetwork) { graphNetwork.destroy(); graphNetwork = null; }
        if (loading) loading.style.display = 'none';
        safeSetHTML(container, N.Components.skeleton.emptyState('share-2', 'Knowledge Graph', 'No connections found. Memories with relationships will appear here.'));
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    var dataSet = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges)
    };

    var physicsEnabled = document.getElementById('graph-physics-toggle').checked;
    var isMobile = window.matchMedia('(max-width: 767px)').matches;

    var options = {
        physics: {
            enabled: physicsEnabled,
            barnesHut: {
                gravitationalConstant: isMobile ? -2000 : -3000,
                centralGravity: isMobile ? 0.4 : 0.3,
                springLength: isMobile ? 80 : 120,
                springConstant: 0.04,
                damping: isMobile ? 0.12 : 0.09
            },
            stabilization: { iterations: isMobile ? 80 : 150, fit: true }
        },
        interaction: {
            hover: !isMobile,
            tooltipDelay: 200,
            hideEdgesOnDrag: true,
            hideEdgesOnZoom: true,
            multiselect: false,
            dragNodes: true,
            dragView: true,
            zoomView: true
        },
        nodes: {
            shape: 'dot',
            scaling: { min: isMobile ? 8 : 10, max: isMobile ? 30 : 40 },
            font: { color: _graphFontColor(), size: isMobile ? 9 : 11 }
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
    setGraphFlashDataSet(dataSet); // flash target + timer reset on re-render

    /* Click → open side panel (entity) or the shared mem modal (memory) */
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

    /* Stabilization done → stop physics jitter */
    graphNetwork.once('stabilizationIterationsDone', function() {
        graphNetwork.setOptions({ physics: { stabilization: { enabled: false } } });
    });
}

/* ---- Detail side panel ---- */

function openGraphDetailPanel(data) {
    /* Entity node: compact side-panel info card stays here.
       Memory nodes open the unified mem modal instead (components/mem-modal.js). */
    if (data.kind !== 'entity') {
        N.Components.memModal.open(data.key);
        return;
    }

    var panel   = document.getElementById('graph-detail-panel');
    var overlay = document.getElementById('graph-panel-overlay');
    var body    = document.getElementById('graph-panel-body');

    var entHtml = '<div style="margin-bottom:12px">' +
        '<div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:4px">Entity</div>' +
        '<div style="font-size:1.05rem;font-weight:600;color:var(--text-primary)">' + esc(data.label || data.key) + '</div>' +
        '</div>' +
        '<div style="color:var(--text-secondary);font-size:0.85rem">' +
        esc(data.entity_type || 'entity') + ' &#183; mentioned in ' + (data.mention_count || 0) + ' memories</div>';
    safeSetHTML(body, entHtml);
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

// Register in namespace
Object.assign(N.Features.Graph, {
    loadGraph: loadGraph,
    populateGraphFilters: populateGraphFilters,
    buildVisData: buildVisData,
    buildTooltip: buildTooltip,
    buildEntityTooltip: buildEntityTooltip,
    applyGraphFilters: applyGraphFilters,
    renderNetwork: renderNetwork,
    openGraphDetailPanel: openGraphDetailPanel,
    closeGraphDetailPanel: closeGraphDetailPanel,
    _graphRefilter: _graphRefilter,
    FLASH_COLORS: FLASH_COLORS,
    setGraphFlashDataSet: setGraphFlashDataSet,
    flashNodeOn: flashNodeOn,
    handleWiringEvent: handleWiringEvent,
    connectGraphFlash: connectGraphFlash,
    disconnectGraphFlash: disconnectGraphFlash,
    setFlashEnabled: setFlashEnabled,
    _flashTimers: function () { return flashTimers; },
});
})();
