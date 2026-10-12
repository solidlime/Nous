/* ================================================================
 *  Knowledge Graph — vis-network interactive memory visualization
 *  (+ Firing Mode — multi-hop 記憶探索のリアルタイム演出。末尾の
 *    追加モジュール N.Features.GraphFire がモードトグルで共存する)
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

/* 動作系 relation（紫=どうする）。それ以外は状態系として既定エッジ色。 */
var ACTION_RELATIONS = { created: true, manages: true };

function _graphFontColor() {
    return document.documentElement.classList.contains('light') ? '#1e1b4b' : '#f1f5f9';
}
function _graphEdgeColor(type, relation) {
    var isLight = document.documentElement.classList.contains('light');
    if (type === 'related') {
        return {
            color:     isLight ? 'rgba(0,82,204,0.75)' : 'rgba(0,122,255,0.85)',
            highlight: isLight ? '#0051d5' : '#60a5fa',
            hover:     isLight ? '#0051d5' : '#60a5fa'
        };
    }
    /* 動作系 relation だけ紫（=どうする）。状態系（knows / located_in 等）
       は「動作」ではないので既定のエッジ色へ落とす。 */
    if (type === 'relation' && ACTION_RELATIONS[relation]) {
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

/* 「記憶の構成要素」4色マッピング（新規フィールド/backfill なし、表示時に
   API 既存値から導出）。
   4色は entity_type の上位概念ではなく【表示層のバケット】として定義し、
   中間語彙(entity_type) → 色バケット の写像をここ1箇所に集約する。
   語彙が増えても色設計は壊れない（未知語彙は自動的に既定グレー）。
   バケット: who=誰が(緑) / what=なにを(黄) / how=どうする(紫, relation 側) /
             feel=きもち(ピンク, memory 枠 側)。
   person|agent が緑（agent は将来の LLM typist 用の受け口、今は到来しない）。
   place / concept / event / organization は現状バケット無し → 灰。 */
var ENTITY_TYPE_BUCKET = {
    person: 'who',
    agent:  'who',
    thing:  'what'
};
var BUCKET_FILL = {
    who:  '#30d158',   /* 緑 = 誰が */
    what: '#ffd60a'    /* 黄 = なにを */
};
var ENTITY_FILL_DEFAULT = '#94a3b8';

/* 型付け経路が信頼できるものだけ着色する。typed_by が無い/未知なら無色。
   regex 抽出はカタカナを person と断定できない（entity として保存される）
   ため、typist（LLM 型付け）実装前は全 entity が灰のまま = 正しい状態。
   typist が metadata.typed_by を書けば自動的に点灯する。 */
var TRUSTED_TYPED_BY = { llm: true, sudachi: true, regex: true };
function entityFillColor(entityType, typedBy) {
    if (!TRUSTED_TYPED_BY[typedBy]) return ENTITY_FILL_DEFAULT;
    var bucket = ENTITY_TYPE_BUCKET[entityType];
    return (bucket && BUCKET_FILL[bucket]) || ENTITY_FILL_DEFAULT;
}

/* memory のピンク枠（=きもち）。neutral は感情なしなので枠は塗り同色。 */
var EMOTION_BORDER_COLOR = '#ff375f';

/* ---- Wiring flash (brain simulation visualization) ---- */

/* Kind → flash color. novelty_gate is the biggest pulse (gold);
   replay_fire blue-purple; recall_boost keeps the existing emphasis. */
var FLASH_COLORS = {
    novelty_gate: '#ffd60a',
    replay_fire: '#7c7cf0',
    recall_boost: '#30d158',
    link_fire: '#bf5af2',
    ppr_hit: '#007aff',
    /* 発火モード（multi-hop 記憶探索）用 — 既存5色は不変 */
    decision_pass: '#30d158',
    decision_reject: '#48484a',
    /* fail-open: judge を適用しなかった事実（engine.py の no_candidates /
       judge_unavailable / parse_failed）。reject の暗灰 #48484a と混同
       しないよう、明るい無彩色で「判定していない」を表す */
    decision_bypass: '#8e8e93',
    hop_start: '#ff9f0a',
    hop_stop: '#64d2ff',
    /* prompt_inject（Phase 12/13）: system プロンプトへの記憶挿入の確定。
       pink は「話に使った」バッジの枠色としても使う。 */
    prompt_inject: '#ff375f'
};

/* 未知 kind の縮退方針（graph.js / wiring.js / resonance.js で統一）:
   下の明示除外リスト以外はフォールバック色で描く。これで「色マップに
   kind を足し忘れると表示が黙る」型のバグが構造的に死ぬ。
   除外は「別の場所で表示される」等の理由があるものだけを載せる。 */
var FLASH_KIND_EXCLUDE = {
    /* 独り言はチャット側の 💭 バブル（chat-send.js）が受ける表示専用
       イベント。chat/memory-panel/wiring.js の WIRING_EXCLUDE と対。 */
    monologue: true
};
var FLASH_FALLBACK_COLOR = '#8e8e93';
function flashColor(kind) {
    if (FLASH_COLORS[kind]) return FLASH_COLORS[kind];
    if (FLASH_KIND_EXCLUDE[kind]) return null;
    return FLASH_FALLBACK_COLOR;
}
var FLASH_RESTORE_MS = 500;
var FLASH_PULSE = { novelty_gate: 2.0, default: 1.6 };
var flashTimers = {}; // per-node generation token: exactly one timer per node
var flashBases = {};  // original node data captured at rest — restore source
var graphDataSet = null;

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
    var color = flashColor(kind);
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
    if (N.Core.streamSocket('graph-flash')) return; // single-flight
    // EventSource cannot send X-Persona headers — pass persona via query param
    // (same channel as the chat wiring feed; server resolves it in deps.py).
    // Rides the shared core stream manager — backoff reconnect now matches
    // the main stream (previously: no reconnect at all).
    N.Core.connectStream('graph-flash', {
        url: function () {
            return '/api/memory/wiring/stream' +
                (S.persona ? '?persona=' + encodeURIComponent(S.persona) : '');
        },
        handlers: {
            wiring: function (e) {
                var ev;
                try { ev = JSON.parse(e.data); } catch (err) { return; }
                handleWiringEvent(ev);
            },
        },
    });
}

function disconnectGraphFlash() {
    N.Core.disconnectStream('graph-flash');
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
            var entColor = entityFillColor(n.entity_type, n.typed_by);
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
        /* 塗りは従来どおり emotion 色。neutral 以外は枠をピンクにして
           「きもち」を表現する（枠/塗りは別チャネル。発火後もこの色へ復帰） */
        var borderColor = (n.emotion && n.emotion !== 'neutral') ? EMOTION_BORDER_COLOR : emoColor;
        return {
            id: n.key,
            label: nodeLabel,
            title: buildTooltip(n),
            size: sz,
            color: {
                background: emoColor,
                border: borderColor,
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
            color: _graphEdgeColor(e.type, e.relation),
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
    flashColor: flashColor,
    setGraphFlashDataSet: setGraphFlashDataSet,
    flashNodeOn: flashNodeOn,
    handleWiringEvent: handleWiringEvent,
    connectGraphFlash: connectGraphFlash,
    disconnectGraphFlash: disconnectGraphFlash,
    setFlashEnabled: setFlashEnabled,
    _flashTimers: function () { return flashTimers; },
    getGraphData: function () { return graphData; },
});
})();

/* ================================================================
 *  FIRING MODE — multi-hop 記憶探索のリアルタイム演出
 *  別 IIFE として追記（既存の全体グラフビューとフラッシュ層は
 *  無改変、モードトグルで共存）。UI DOM もここから #tab-graph に
 *  注入する（設定サイドバーが並行実装中のため Python 側は触らない）。
 *  Namespace: N.Features.GraphFire
 *  ================================================================ */
;(function() {
"use strict";

var G = N.Features.Graph;
var api = N.Core.api;
var truncate = N.Core.truncate;
var FIRE_CHANNEL = 'graph-fire'; /* 一意チャンネル名（graph-flash と分離） */
var SEARCH_LIMIT = 20;
var FIRE_DEFAULT_HOPS = 2; /* 既定ホップ数（送信時 1..5 に clamp） */

/* ---- 状態 ---- */
var fireUI = null;   /* 注入した DOM 参照（なければ UI 関連は何もしない） */
var fireState = {
    mode: false,
    turnMode: false,  /* chat 由来の発火を turn_id で束ねる表示モード */
    session: null,     /* { requestId, turnId, hops, decision, results: Map, memories: {}, hop, done } */
    dataSet: null,     /* { nodes, edges } vis DataSets（テストフックで差し替え可） */
    network: null,
    edgeIndex: {},     /* "a|b" → { id, type }（辞書順 a<b に正規化） */
    graphEdgeMap: {},  /* 全体グラフの tag/related エッジ "a|b" → edge（クラスタ基盤） */
    pulses: {},        /* パルス復帰タイマ（ノードid / edge:xx キー毎, 新しい方が勝つ） */
    fadeGen: 0,        /* 枝刈りフェードの世代トークン（新実行で無効化） */
    lightTimer: null,  /* 順次点灯キューのタイマ */
};
var fireBases = {};  /* ノード静止時スナップショット（パルス復帰の基準） */
var lightQueue = [];

/* ---- 共通ヘルパ ---- */

/* prefers-reduced-motion: 動きを短縮・即時化するが状態変化自体は残す */
function _reduceMotion() {
    return typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function _fontColor() {
    return document.documentElement.classList.contains('light') ? '#1e1b4b' : '#f1f5f9';
}

function _uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        try { return crypto.randomUUID(); } catch (e) { /* フォールバックへ */ }
    }
    /* RFC4122 v4 形状の擬似 UUID */
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        var r = Math.random() * 16 | 0;
        return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
}

function _el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) {
        Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    }
    if (text != null) e.textContent = text; /* 結果パネル系は textContent のみ（innerHTML 禁止） */
    return e;
}

function setStatus(text) {
    if (fireUI && fireUI.status) fireUI.status.textContent = text;
}

/* 生値の表示 — 未計測(null/NaN) は「—」。0 と混同させない */
function _numText(v, digits) {
    if (v == null || !isFinite(Number(v))) return '\u2014';
    return Number(v).toFixed(digits);
}

/* content 抜粋 — 最大120字（超過分は…で打ち切り） */
function excerpt(str) {
    str = String(str == null ? '' : str);
    if (str.length <= 120) return str;
    return str.slice(0, 119) + '\u2026';
}

/* ---- ノードパルス（速度・強さにジッタ。等速・等間隔は禁止） ---- */

function pulseNode(id, kind, opts) {
    opts = opts || {};
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes || !id) return false;
    var color = G.flashColor(kind);
    if (!color) return false;
    var node = nodes.get(id);
    if (!node) return false;
    if (fireState.pulses[id]) { clearTimeout(fireState.pulses[id]); delete fireState.pulses[id]; }
    var base = fireBases[id] || { size: node.size || 10, color: node.color };
    var scale = (opts.scale || 1.4) * (0.9 + Math.random() * 0.45); /* ジッタ: 振幅 */
    var held = {
        background: color, border: color,
        highlight: base.color.highlight, hover: base.color.hover
    };
    nodes.update({ id: id, color: held, size: base.size * scale });
    if (opts.hold) {
        /* decision_pass: 緑で保持 — 以後のパルス復帰もこの色に戻す */
        fireBases[id] = { size: base.size, color: held };
        return true;
    }
    var dur = _reduceMotion() ? 1 : (opts.duration || 520) * (0.7 + Math.random() * 0.8); /* ジッタ: 継続時間 */
    fireBases[id] = base;
    fireState.pulses[id] = setTimeout(function () {
        delete fireState.pulses[id];
        delete fireBases[id];
        nodes.update({ id: id, color: base.color, size: base.size });
    }, dur);
    return true;
}

/* ---- 順次点灯キュー（不揃いな間隔 = 生物的） ---- */

function queueLight(id, kind, opts) {
    if (!id) return false;
    lightQueue.push([id, kind, opts || {}]);
    if (!fireState.lightTimer) pumpLightQueue();
    return true;
}

function pumpLightQueue() {
    fireState.lightTimer = null;
    if (!lightQueue.length) return;
    var item = lightQueue.shift();
    pulseNode(item[0], item[1], item[2]);
    if (lightQueue.length) {
        var gap = _reduceMotion() ? 0 : 70 + Math.random() * 130; /* ジッタ: 点灯間隔 */
        fireState.lightTimer = setTimeout(pumpLightQueue, gap);
    }
}

/* ---- シーン（発火モード用サブグラフ） ---- */

function resetFireScene() {
    var st = fireState;
    Object.keys(st.pulses).forEach(function (k) { clearTimeout(st.pulses[k]); });
    st.pulses = {};
    fireBases = {};
    lightQueue = [];
    if (st.lightTimer) { clearTimeout(st.lightTimer); st.lightTimer = null; }
    st.fadeGen++; /* 前回実行の枝刈りフェード連鎖を世代トークンで無効化 */
    st.edgeIndex = {};
    st.graphEdgeMap = {};
    if (st.dataSet) { st.dataSet.nodes.clear(); st.dataSet.edges.clear(); }
}

function setFireDataSet(ds) {
    Object.keys(fireState.pulses).forEach(function (k) { clearTimeout(fireState.pulses[k]); });
    fireState.pulses = {};
    fireState.dataSet = ds || null;
    if (ds) fireState.network = null;
}

function ensureFireDataSet() {
    if (fireState.dataSet) return fireState.dataSet;
    if (typeof vis === 'undefined') return null;
    var ds = { nodes: new vis.DataSet([]), edges: new vis.DataSet([]) };
    var container = document.getElementById('graph-fire-container');
    var isMobile = window.matchMedia('(max-width: 767px)').matches;
    var options = {
        /* tag エッジを基盤に有機的にクラスタが形成されるフォース配置。
           中心重力を弱く・スプリングを強めにして同タグ群が塊になる。
           規則的な円形配置は使わない（初期配置もランダムのまま）。 */
        physics: {
            barnesHut: {
                gravitationalConstant: isMobile ? -4500 : -6500,
                centralGravity: 0.08,
                springLength: isMobile ? 60 : 90,
                springConstant: 0.09,
                damping: 0.14,
                avoidOverlap: 0.3
            },
            stabilization: { iterations: isMobile ? 60 : 100, fit: true }
        },
        interaction: { hover: !isMobile, tooltipDelay: 200, dragNodes: true, dragView: true, zoomView: true },
        nodes: { shape: 'dot', font: { color: _fontColor(), size: 10, face: 'system-ui' } },
        edges: { smooth: { type: 'continuous', roundness: 0.35 } }
    };
    fireState.network = new vis.Network(container, ds, options);
    fireState.network.once('stabilizationIterationsDone', function () {
        if (fireState.network) {
            fireState.network.setOptions({ physics: { stabilization: { enabled: false } } });
        }
    });
    fireState.dataSet = ds;
    return ds;
}

/* ツールチップは DOM 要素で渡す（vis は文字列を HTML として解釈するため XSS 対策） */
function _nodeTitle(text) {
    var d = document.createElement('div');
    d.style.cssText = 'background:#1e293b;color:#e2e8f0;border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.5;max-width:300px;white-space:normal;word-break:break-word;';
    d.textContent = String(text == null ? '' : text);
    return d;
}

function _nodeVisual(m, isSeed) {
    var emo = N.Core.EMOTION_COLORS[m.emotion] || (m.content ? '#64748b' : '#475569');
    var baseSize = isSeed ? 14 + (m.score || 0.5) * 22 : 10 + (m.importance || 0.5) * 14;
    /* シナプス風: ノードサイズにも不揃いさを持たせる */
    var size = baseSize * (0.9 + Math.random() * 0.25);
    var content = m.content || m.key || 'Unknown';
    return {
        id: m.key,
        label: truncate(String(content), 20) || String(m.key || 'Unknown'),
        title: _nodeTitle(content),
        shape: 'dot',
        size: size,
        color: {
            background: emo, border: emo,
            highlight: { background: emo, border: '#fff' },
            hover: { background: emo, border: '#fff' }
        },
        font: { color: _fontColor(), size: 10, face: 'system-ui' },
        borderWidth: 2,
        _mem: m,
        _memContent: !!(m.content)
    };
}

function ensureFireNode(key, mem, isSeed) {
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes || !key) return null;
    if (nodes.get(key)) {
        /* メモリ情報（content 等）を後から得た場合はラベルだけ更新（色は触らない） */
        var cur = nodes.get(key);
        if (mem && mem.content && !cur._memContent) {
            nodes.update({ id: key, label: truncate(String(mem.content), 20), title: _nodeTitle(mem.content), _memContent: true });
        }
        return key;
    }
    var m = mem || _memoryFor(key) || { key: key };
    nodes.update(_nodeVisual(m, isSeed));
    absorbGraphEdges(key);
    return key;
}

/* 全体グラフの tag/related エッジをクラスタ基盤として取り込む */
function buildGraphEdgeMap() {
    var map = {};
    var g = G.getGraphData ? G.getGraphData() : null;
    ((g && g.edges) || []).forEach(function (e) {
        if (e.type !== 'tag' && e.type !== 'related') return;
        map[e.source + '|' + e.target] = e;
        map[e.target + '|' + e.source] = e;
    });
    fireState.graphEdgeMap = map;
}

function _normKey(a, b) { return a < b ? a + '|' + b : b + '|' + a; }

function _graphEdgeType(a, b) {
    var e = fireState.graphEdgeMap[_normKey(a, b)];
    return e ? e.type : '';
}

/* 新規ノードがシーンに入ったら、既に見えている隣接ノードへ tag/related エッジを張る */
function absorbGraphEdges(key) {
    var g = G.getGraphData ? G.getGraphData() : null;
    var all = (g && g.edges) || [];
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes) return;
    for (var i = 0; i < all.length; i++) {
        var e = all[i];
        if (e.type !== 'tag' && e.type !== 'related') continue;
        var other = e.source === key ? e.target : (e.target === key ? e.source : null);
        if (!other || other === key) continue;
        if (nodes.get(other)) ensureFireEdge(key, other, e.type);
    }
}

function _fireEdgeColor(type) {
    if (type === 'related') return 'rgba(0,122,255,0.55)';
    if (type === 'tag') return 'rgba(167,139,250,0.55)';
    return 'rgba(100,200,255,0.4)'; /* 仮設エッジ: 伝播を見せるための連結線 */
}

function ensureFireEdge(a, b, type) {
    var edges = fireState.dataSet && fireState.dataSet.edges;
    if (!edges || !a || !b || a === b) return null;
    var k = _normKey(a, b);
    if (fireState.edgeIndex[k]) return fireState.edgeIndex[k];
    var color = _fireEdgeColor(type);
    var width = type === 'tag' ? 2 : (type === 'related' ? 1.8 : 1.2);
    var edge = {
        id: 'fe:' + k,
        from: a, to: b,
        dashes: type ? false : [2, 5],
        width: width,
        color: { color: color, highlight: color, hover: color, opacity: 1 },
        smooth: { type: 'continuous', roundness: 0.35 },
        _fireBase: { color: color, width: width }
    };
    edges.update(edge);
    fireState.edgeIndex[k] = { id: edge.id, type: type || '' };
    return fireState.edgeIndex[k];
}

/* エッジを光らせる（連鎖方向のグロー）。減光時間もジッタ */
function glowEdge(a, b) {
    var edges = fireState.dataSet && fireState.dataSet.edges;
    if (!edges) return;
    var rec = fireState.edgeIndex[_normKey(a, b)];
    if (!rec) return;
    var e = edges.get(rec.id);
    if (!e || !e._fireBase) return;
    var tkey = 'edge:' + rec.id;
    if (fireState.pulses[tkey]) { clearTimeout(fireState.pulses[tkey]); delete fireState.pulses[tkey]; }
    var glow = G.FLASH_COLORS.link_fire;
    edges.update({ id: rec.id, color: { color: glow, highlight: glow, hover: glow, opacity: 1 }, width: e._fireBase.width + 1.6 });
    var ms = _reduceMotion() ? 1 : 380 + Math.random() * 420;
    fireState.pulses[tkey] = setTimeout(function () {
        delete fireState.pulses[tkey];
        /* 枝刈り済みのエッジは復活させない（グロー復帰と prune は競合する） */
        if (!edges.get(rec.id)) return;
        edges.update({ id: rec.id, color: { color: e._fireBase.color, highlight: e._fireBase.color, hover: e._fireBase.color, opacity: 1 }, width: e._fireBase.width });
    }, ms);
}

/* ---- メモリ情報と結果累積 ---- */

function _memoryFor(key) {
    var s = fireState.session;
    if (s && s.memories && s.memories[key]) return s.memories[key];
    var g = G.getGraphData ? G.getGraphData() : null;
    var nodes = (g && g.nodes) || [];
    for (var i = 0; i < nodes.length; i++) {
        if (nodes[i].key === key && nodes[i].kind !== 'entity') return nodes[i];
    }
    return null;
}

function accumulateResult(key, patch) {
    var s = fireState.session;
    if (!s || !key) return null;
    var r = s.results.get(key);
    if (!r) {
        var m = _memoryFor(key) || {};
        r = { key: key, content: m.content || '', tags: (m.tags || []).slice(), score: 0, pass: null, prob: null,
              sim: null, jev: null, time: null, simModel: null, used: false };
        s.results.set(key, r);
    }
    if (patch.used) r.used = true;
    if (patch.score && patch.score > r.score) r.score = patch.score;
    if (patch.weight != null) r.prob = patch.weight;
    if (patch.pass === true || patch.pass === false) r.pass = patch.pass;
    /* 生値は 0 と「未計測(null)」を区別して保持する */
    if (patch.sim != null) r.sim = patch.sim;
    if (patch.simModel != null) r.simModel = patch.simModel;
    if (patch.jev != null) r.jev = patch.jev;
    if (patch.time != null) r.time = patch.time;
    return r;
}

function ingestResults(data) {
    var s = fireState.session;
    if (!s || !data) return;
    s.memories = s.memories || {};
    (data.results || []).forEach(function (r) {
        var m = r.memory || {};
        if (!m.key) return;
        s.memories[m.key] = Object.assign(s.memories[m.key] || {}, m);
        accumulateResult(m.key, { score: Number(r.score) || 0 });
        ensureFireNode(m.key, s.memories[m.key], true); /* シードノード: 先に配置し順次点灯を待つ */
    });
    renderResults();
}

/* ---- イベント契約ハンドラ ----
   hop_start → seed 順次点灯 → propagate（tag/related エッジ沿い）
   → converge → decision_pass / decision_reject → hop_stop(meta.reason)。
   kind は大小文字を正規化して照合し、未知 kind はエラー扱いしない。 */

function handleFireEvent(ev) {
    if (!fireState.mode || !ev || typeof ev !== 'object') return false;
    var kind = String(ev.kind || '').toLowerCase();
    var meta = ev.meta || {};
    var s = fireState.session;
    if (fireState.turnMode) {
        /* chat 由来は turn_id 相関。1 発話は複数の request_id に跨るため、
           request_id ではなく turn_id の一致で束ね、変わり目を連鎖の境界にする
           （prompt_inject は request_id を持たない — wiring_events.py 契約）。 */
        if (meta.turn_id == null) return false;
        if (!s || s.turnId !== meta.turn_id) s = fireState.session = openTurnSession(meta.turn_id);
    } else {
        /* 手動 FIRE: meta.request_id が自分の UUID のイベントのみ消費する（不変） */
        if (!s || !meta.request_id || meta.request_id !== s.requestId) return false;
    }
    /* hop_stop は終端 — サーバは停止後に converge 群 (engine.py: hop_stop → _emit_converge)
       を同時刻に後発させるため、ガードが無いと「収束中…」が終端表示を上書きする。
       hop_start だけは turn モードの同ターン次連鎖の再始動として通す。 */
    if (s.done && kind !== 'hop_start') return false;
    switch (kind) {
        case 'hop_start':       return onHopStart(ev, meta);
        case 'ppr_hit':         return onPprHit(ev, meta);
        case 'propagate':       return onPropagate(ev, meta);
        case 'converge':        return onConverge(ev, meta);
        case 'decision_pass':   return onDecision(ev, meta, true);
        case 'decision_reject': return onDecision(ev, meta, false);
        case 'hop_stop':        return onHopStop(ev, meta);
        case 'decision_bypass': return onDecisionBypass(ev, meta);
        case 'prompt_inject':   return onPromptInject(ev, meta);
        default: return false; /* 未知 kind: エラー扱いしない */
    }
}

/* 発話(turn)単位の連鎖を新規に開く。1 発話 = 1 turn_id が連鎖の単位。 */
function openTurnSession(turnId) {
    resetFireScene();
    ensureFireDataSet();
    buildGraphEdgeMap();
    return {
        requestId: null, turnId: turnId, hops: FIRE_DEFAULT_HOPS, decision: false,
        results: new Map(), memories: {}, hop: 0, done: false, bypassReason: ''
    };
}

function onHopStart(ev, meta) {
    var s = fireState.session;
    var hop = parseInt(meta.hop, 10);
    s.done = false; /* turn モードの同ターン次 request の連鎖を再始動 */
    s.hop = isNaN(hop) ? s.hop + 1 : hop;
    setStatus('HOP ' + s.hop + '/' + s.hops + ' \u30fb 探索中\u2026');
    s.bypassReason = ''; /* この hop の fail-open 注記は hop 単位で持ち越さない */
    /* seed 点灯の担い手は ingestResults(ensureFireNode) + onPprHit に一本化した。
       hop_start は retrieve 前 emit で seeds/source を持たないため、ここで点灯する
       分岐は構造的に死んでいた。 */
    return true;
}

function onPprHit(ev, meta) {
    var key = ev.source || ev.target;
    if (!key) return false;
    ensureFireNode(key, null, true);
    accumulateResult(key, { score: Number(ev.weight) || 0 });
    /* seed 点灯（ppr_hit = 青）。ジッタ付きキューで不揃いに順次点灯 */
    return queueLight(key, 'ppr_hit', { scale: 1.5, duration: 640 });
}

function onPropagate(ev, meta) {
    var a = ev.source, b = ev.target;
    if (!a || !b || a === b) return false;
    ensureFireNode(a);
    ensureFireNode(b);
    /* tag/related エッジ沿いの連鎖点灯（グラフになければ仮設エッジ） */
    var rec = ensureFireEdge(a, b, _graphEdgeType(a, b));
    if (rec) glowEdge(a, b);
    accumulateResult(b, { score: Number(ev.weight) || 0 });
    /* 伝播ディレイにもジッタ */
    var delay = _reduceMotion() ? 0 : Math.random() * 120;
    setTimeout(function () { pulseNode(b, 'link_fire', { scale: 1.3, duration: 430 }); }, delay);
    return true;
}

function onConverge(ev, meta) {
    var hub = ev.target || ev.source;
    if (!hub) return false;
    ensureFireNode(hub);
    var s = fireState.session;
    setStatus('HOP ' + s.hop + '/' + s.hops + ' \u30fb 収束中\u2026');
    return pulseNode(hub, 'hop_stop', { scale: 1.9, duration: 780 }); /* 水色の収束パルス */
}

function onDecision(ev, meta, pass) {
    var key = ev.source || ev.target;
    if (!key) return false;
    ensureFireNode(key);
    /* 生値併記（Q3）: 積だけでは「なぜ差が出たか」を復元できない。
       jev = 判定確率 / sim = cosine（keyword/fts 由来は未計測 = null）/ time = 順位付けに
       実際に掛かった倍率（floor 適用後の実効値）/ simModel = クエリ側 encoder 名 */
    accumulateResult(key, {
        pass: pass,
        weight: pass ? (Number(ev.weight) || null) : null,
        jev: meta.jev == null ? null : Number(meta.jev),
        sim: meta.cosine == null ? null : Number(meta.cosine),
        simModel: meta.sim_model == null ? null : String(meta.sim_model),
        time: meta.time_weight == null ? null : Number(meta.time_weight)
    });
    if (pass) {
        /* decision_pass: 緑で保持 */
        return pulseNode(key, 'decision_pass', { hold: true, scale: 1.35 });
    }
    /* decision_reject: ノードを dim + 枝（エッジ）をアニメーション付きでフェード消去 */
    dimNode(key);
    pruneBranches(key);
    return true;
}

/* fail-open の reason → 注記文。reason ごとに変える（1 文案の全 reason 流用は新たな誤報になる） */
function _bypassText(reason) {
    if (reason === 'no_candidates') return '\u5019\u88dc\u306a\u3057';
    if (reason === 'judge_unavailable' || reason === 'parse_failed') {
        return '\u5224\u5b9a\u30b9\u30ad\u30c3\u30d7\u30fb\u5168\u5019\u88dc\u63a1\u7528';
    }
    return '\u5224\u5b9a\u4e0d\u901a\u904e'; /* 未知 reason の縮退 */
}

/* decision_bypass = fail-open で「判定を適用しなかった」事実（却下ではない）。
   ノード演出はしない — 却下と同じ見え方にすると嘘を描くことになる。沈黙も避けるため
   reason をステータスへ注記し、同じ hop の hop_stop が終端表示に併記する。 */
function onDecisionBypass(ev, meta) {
    var s = fireState.session;
    if (!s) return false;
    s.bypassReason = String(meta.reason || '');
    setStatus('HOP ' + s.hop + '/' + s.hops + ' \u30fb ' + _bypassText(s.bypassReason));
    return true;
}

/* prompt_inject: そのターンで system プロンプトへ挿入された記憶（挿入の確定）。
   LLM が実際にその記憶を使った証明ではないため「使用」ではなく「話に使った」
   バッジ相当の pink 枠 + _used フラグで示す（wiring_events.py 契約）。 */
function onPromptInject(ev, meta) {
    var key = ev.source || ev.target;
    if (!key) return false;
    ensureFireNode(key, null, true);
    accumulateResult(key, { used: true });
    markUsedInReply(key);
    return queueLight(key, 'prompt_inject', { scale: 1.4, duration: 620 });
}

/* 挿入された記憶のノードをピンク枠で保持する（パルス復帰後もバッジは残す） */
function markUsedInReply(key) {
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes) return;
    var node = nodes.get(key);
    if (!node) return;
    var base = fireBases[key] || { size: node.size || 10, color: node.color };
    var pink = G.FLASH_COLORS.prompt_inject;
    var held = {
        background: base.color.background, border: pink,
        highlight: base.color.highlight, hover: base.color.hover
    };
    nodes.update({ id: key, color: held, borderWidth: 4, _used: true });
    fireBases[key] = { size: base.size, color: held };
}

function dimNode(key) {
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes) return;
    var node = nodes.get(key);
    if (!node) return;
    if (fireState.pulses[key]) { clearTimeout(fireState.pulses[key]); delete fireState.pulses[key]; }
    var base = fireBases[key] || { size: node.size || 10, color: node.color };
    var dim = G.FLASH_COLORS.decision_reject;
    var held = {
        background: dim, border: dim,
        highlight: base.color.highlight, hover: base.color.hover
    };
    /* reject されたノードは dim のまま固定（復帰タイマなし）。以後のパルス復帰も dim に戻す */
    nodes.update({
        id: key,
        color: held,
        size: base.size * 0.7,
        font: { color: 'rgba(148,163,184,0.4)', size: 9, face: 'system-ui' }
    });
    fireBases[key] = { size: base.size * 0.7, color: held };
}

/* 枝刈り: reject ノードに繋がるエッジをフェードで消す（アニメーション付き） */
function pruneBranches(key) {
    var edges = fireState.dataSet && fireState.dataSet.edges;
    if (!edges) return;
    var ids = [];
    Object.keys(fireState.edgeIndex).forEach(function (k) {
        var parts = k.split('|');
        if (parts[0] === key || parts[1] === key) ids.push(fireState.edgeIndex[k].id);
    });
    if (!ids.length) return;
    var dur = _reduceMotion() ? 0 : 520 + Math.random() * 320; /* ジッタ: 枝刈り時間 */
    if (!dur) { edges.remove(ids); return; }
    var gen = ++fireState.fadeGen;
    var steps = 7;
    var step = 0;
    (function tick() {
        if (gen !== fireState.fadeGen) return; /* 新実行 / リセットで無効化 */
        step++;
        var a = Math.max(1 - step / steps, 0);
        ids.forEach(function (id) {
            var e = edges.get(id);
            if (e && e._fireBase) {
                edges.update({
                    id: id,
                    color: { color: e._fireBase.color, highlight: e._fireBase.color, hover: e._fireBase.color, opacity: a },
                    width: Math.max(e._fireBase.width * a, 0.15)
                });
            }
        });
        if (step < steps) setTimeout(tick, dur / steps);
        else edges.remove(ids);
    })();
}

function onHopStop(ev, meta) {
    var s = fireState.session;
    var reason = String(meta.reason || '');
    s.done = true;
    /* fail-open の事実は終端表示に併記する（ここで bypass の setStatus を上書きさせない） */
    var note = s.bypassReason ? ' \u30fb ' + _bypassText(s.bypassReason) : '';
    if (reason === 'sufficiency') {
        setStatus('\u53ce\u675f \u2014 \u5341\u5206\u6027\u306b\u9054\u3057\u307e\u3057\u305f (sufficiency)' + note);
        finaleBloom();
    } else if (reason === 'max_hops') {
        setStatus('hop \u4e0a\u9650\u306b\u5230\u9054 (max_hops)' + note);
        finaleQuiet();
    } else if (reason === 'no_candidates') {
        setStatus('\u5019\u88dc\u306a\u3057 \u2014 \u53ce\u675f\u305b\u305a (no_candidates)' + note);
        finaleFade();
    } else {
        setStatus('\u63a2\u7d22\u5b8c\u4e86' + note);
    }
    renderResults();
    return true;
}

/* ---- 締めの演出 — hop_stop の meta.reason で変える ---- */

function _passedKeys() {
    var out = [];
    fireState.session.results.forEach(function (r, key) { if (r.pass) out.push(key); });
    return out;
}

function sceneNodeIds() {
    var nodes = fireState.dataSet && fireState.dataSet.nodes;
    if (!nodes) return [];
    var all = nodes.get();
    return (Array.isArray(all) ? all : []).map(function (n) { return n.id; });
}

/* sufficiency: 収束の華 — pass ノードが不揃いなタイミングで発光する */
function finaleBloom() {
    var keys = _passedKeys();
    if (!keys.length) keys = sceneNodeIds();
    keys.forEach(function (k) {
        if (_reduceMotion()) { pulseNode(k, 'decision_pass', { hold: true, scale: 1.2 }); return; }
        setTimeout(function () {
            pulseNode(k, 'decision_pass', { scale: 1.8, duration: 720 }); /* ジッタ: 発光間隔 */
        }, 60 + Math.random() * 420);
    });
}

/* max_hops: 静かな締め — 一度小さく脈打って静止へ */
function finaleQuiet() {
    sceneNodeIds().forEach(function (k) {
        pulseNode(k, 'hop_stop', { scale: 1.25, duration: 420 });
    });
}

/* no_candidates: 収束なしの収束 — 点いたノードがぼんやりと薄まる */
function finaleFade() {
    if (_reduceMotion()) return;
    sceneNodeIds().forEach(function (k) {
        setTimeout(function () {
            pulseNode(k, 'decision_reject', { scale: 0.95, duration: 900 });
        }, Math.random() * 300);
    });
}

/* ---- 結果パネル: 全 hop 累積の上位20件。
        textContent のみで構築（innerHTML 禁止・XSS 回避） ---- */
function renderResults() {
    var list = fireUI && fireUI.resultsList;
    if (!list) return;
    var s = fireState.session;
    if (fireUI.results) fireUI.results.style.display = s ? '' : 'none';
    var rows = s ? Array.from(s.results.values()) : [];
    rows.sort(function (a, b) { return b.score - a.score; });
    rows = rows.slice(0, SEARCH_LIMIT);
    list.textContent = ''; /* クリアも innerHTML を使わない */
    if (!rows.length) {
        list.appendChild(_el('li', { 'class': 'nfire-empty' }, '\u7d50\u679c\u306f\u307e\u3060\u3042\u308a\u307e\u305b\u3093'));
        return;
    }
    rows.forEach(function (r) {
        var li = _el('li', { 'class': 'nfire-row' });
        var head = _el('div', { 'class': 'nfire-row-head' });
        if (r.key) head.appendChild(_el('span', { 'class': 'nfire-key' }, r.key));
        head.appendChild(_el('span', { 'class': 'nfire-score' }, (r.score || 0).toFixed(4)));
        if (r.pass === true) {
            var p = (r.prob != null && isFinite(r.prob)) ? ' ' + Math.round(r.prob * 100) + '%' : '';
            head.appendChild(_el('span', { 'class': 'nfire-badge nfire-pass' }, 'PASS' + p));
        } else if (r.pass === false) {
            head.appendChild(_el('span', { 'class': 'nfire-badge nfire-reject' }, 'REJECT'));
        }
        if (r.used) {
            /* prompt_inject: プロンプト挿入の確定（使用の証明ではない） */
            head.appendChild(_el('span', { 'class': 'nfire-badge nfire-used' }, '\u8a71\u306b\u4f7f\u3063\u305f'));
        }
        li.appendChild(head);
        if (r.pass === true || r.pass === false) {
            /* 生値併記（Q3）: 3 つの生値を並べる。積（.nfire-score）と視覚的に区別する。
               未計測は「—」— 0 と混同させない（keyword/fts 由来の cosine は null）。
               time は順位付けに実際に掛かった倍率（floor 適用後）。 */
            var simModel = r.simModel ? String(r.simModel) : '';
            var valsAttrs = { 'class': 'nfire-vals' };
            if (simModel) {
                /* cosine は Qdrant stored vector との積。保証できるのはクエリ側 encoder 名だけ
                   （移行中に stored が旧 encoder なら真の類似度の作成モデルは混合）。 */
                valsAttrs.title = 'クエリ埋め込み: ' + simModel;
            }
            li.appendChild(_el('div', valsAttrs, [
                'sim ' + _numText(r.sim, 3) + (simModel ? ' (' + simModel + ')' : ''),
                'jev ' + _numText(r.jev, 2),
                'time ' + (r.time == null ? '\u2014' : 'x' + Number(r.time).toFixed(2))
            ].join(' \u30fb ')));
        }
        if (r.tags && r.tags.length) {
            li.appendChild(_el('div', { 'class': 'nfire-tags' }, r.tags.map(String).join(' \u30fb ')));
        }
        li.appendChild(_el('div', { 'class': 'nfire-content' }, excerpt(r.content || r.key)));
        list.appendChild(li);
    });
}

/* ---- 実行 ---- */

function runFire() {
    if (!fireUI) return false;
    var q = (fireUI.query.value || '').trim();
    if (!q || !S.persona) return false;
    var decision = !!fireUI.decision.checked;
    var hops = parseInt(fireUI.hops.value, 10);
    if (isNaN(hops)) hops = FIRE_DEFAULT_HOPS;
    if (hops < 1) hops = 1;
    if (hops > 5) hops = 5;
    var requestId = _uuid();
    resetFireScene();
    fireState.session = {
        requestId: requestId, hops: hops, decision: decision,
        results: new Map(), memories: {}, hop: 0, done: false, bypassReason: ''
    };
    ensureFireDataSet();
    if (!fireState.dataSet) {
        setStatus('vis-network \u30e9\u30a4\u30d6\u30e9\u30ea\u304c\u5229\u7528\u3067\u304d\u307e\u305b\u3093');
        return false;
    }
    buildGraphEdgeMap();
    connectFireStream(); /* 先に SSE を購読して初期イベントの取りこぼしを防ぐ */
    setStatus('HOP 1/' + hops + ' \u30fb \u767a\u706b\u2026');
    /* 仕様 (#011): GraphFire は「発火の可視化」なので、永続設定 brain_decision_enabled
       (既定 false) とは独立に decision トグル (既定 ON) を送り、判定込みのパイプラインを
       見せる。判定が実際に走らない場合は SSE の decision_bypass (no_api_key /
       no_candidates / judge_unavailable / parse_failed) として観測される。
       設定の無効を UI 上は有効に見せるのは意図したデモ駆動であり、バグではない。 */
    var url = '/api/search/' + encodeURIComponent(S.persona) +
        '?q=' + encodeURIComponent(q) +
        '&decision=' + (decision ? '1' : '0') +
        '&hops=' + hops +
        '&request_id=' + encodeURIComponent(requestId) +
        '&limit=' + SEARCH_LIMIT;
    api(url).then(function (data) {
        /* レスポンス到着と SSE イベントの順序は不定 — どちらでもマージされる */
        var s = fireState.session;
        if (s && s.requestId === requestId) ingestResults(data);
    }).catch(function (e) {
        setStatus('\u63a2\u7d22\u5931\u6557: ' + ((e && e.message) || e));
    });
    renderResults();
    return true;
}

/* ---- SSE 配線（wiring ストリームを一意チャンネルで共用） ---- */

function connectFireStream() {
    if (N.Core.streamSocket(FIRE_CHANNEL)) return; /* single-flight */
    /* EventSource はヘッダを送れない — persona はクエリパラメタで（graph-flash と同じ） */
    N.Core.connectStream(FIRE_CHANNEL, {
        url: function () {
            return '/api/memory/wiring/stream' +
                (S.persona ? '?persona=' + encodeURIComponent(S.persona) : '');
        },
        handlers: {
            wiring: function (e) {
                var ev;
                try { ev = JSON.parse(e.data); } catch (err) { return; }
                handleFireEvent(ev);
            }
        }
    });
}

function disconnectFireStream() {
    N.Core.disconnectStream(FIRE_CHANNEL);
}

/* ---- turn モード ---- */

function setTurnMode(on) {
    fireState.turnMode = !!on;
    if (fireUI && fireUI.turnMode) fireUI.turnMode.checked = fireState.turnMode;
    if (fireState.turnMode) {
        fireState.session = null; /* 手動 FIRE のセッションは持ち越さない */
        if (fireState.mode) connectFireStream();
    }
    return fireState.turnMode;
}

/* ---- モードトグル（全体グラフビューとの共存） ---- */

function setMode(on) {
    fireState.mode = !!on;
    if (!fireUI) return fireState.mode;
    var anchor = document.getElementById('graph-content');
    if (fireState.mode) {
        if (anchor) anchor.style.display = 'none';
        fireUI.root.style.display = '';
        fireUI.toggle.checked = true;
        setStatus('\u30af\u30a8\u30ea\u3092\u5165\u308c\u3066\u300c\u767a\u706b\u300d\u3092\u62bc\u3057\u3066\u306d');
        /* turn モードは手動 FIRE を待たず chat 発火を passive に受ける。 */
        if (fireState.turnMode) connectFireStream();
    } else {
        if (anchor) anchor.style.display = '';
        fireUI.root.style.display = 'none';
        fireUI.toggle.checked = false;
        /* 発火モードを抜けたら入力を初期化（範囲外の値を持ち越さない） */
        fireUI.hops.value = String(FIRE_DEFAULT_HOPS);
        disconnectFireStream();
        resetFireScene();
        fireState.session = null;
    }
    return fireState.mode;
}

/* ---- UI 構築（#tab-graph へ注入。Python 側は触らない） ---- */

var FIRE_CSS = [
    '#graph-fire-status { color: var(--text-muted); font-size: 0.8rem; margin-left: auto; }',
    '.nfire-vals { font-size: 0.72rem; font-family: monospace; color: var(--text-muted); margin-bottom: 2px; font-variant-numeric: tabular-nums; }',
    '.nfire-row { padding: 10px 4px; border-bottom: 1px solid var(--glass-border); }',
    '.nfire-row:last-child { border-bottom: none; }',
    '.nfire-row-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }',
    '.nfire-key { font-size: 0.75rem; font-family: monospace; color: var(--text-primary); }',
    '.nfire-score { font-size: 0.8rem; color: var(--text-secondary); font-variant-numeric: tabular-nums; }',
    '.nfire-badge { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; padding: 2px 8px; border-radius: 999px; }',
    '.nfire-pass { color: #30d158; border: 1px solid rgba(48,209,88,0.45); background: rgba(48,209,88,0.12); }',
    '.nfire-reject { color: #a9a9b0; border: 1px solid rgba(72,72,74,0.6); background: rgba(72,72,74,0.25); }',
    '.nfire-used { color: #ff375f; border: 1px solid rgba(255,55,95,0.5); background: rgba(255,55,95,0.12); }',
    '.nfire-tags { font-size: 0.72rem; color: var(--text-muted); margin-bottom: 2px; }',
    '.nfire-content { font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5; word-break: break-word; }',
    '.nfire-empty { color: var(--text-muted); font-size: 0.85rem; padding: 8px 4px; }'
].join('\n');

function buildFireUI(tab) {
    var style = _el('style');
    style.textContent = FIRE_CSS;
    tab.appendChild(style);

    var anchor = document.getElementById('graph-content');

    /* モードトグルパネル */
    var panel = _el('div', { 'class': 'glass', id: 'graph-fire-panel', style: 'padding:12px 16px;margin-bottom:12px' });
    var toggleLabel = _el('label', { style: 'display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;color:var(--text-secondary);font-size:0.88rem' });
    var toggle = _el('input', { type: 'checkbox', id: 'graph-fire-toggle' });
    toggle.style.accentColor = 'var(--accent-blue)';
    toggleLabel.appendChild(toggle);
    toggleLabel.appendChild(_el('span', null, '\u767a\u706b\u30e2\u30fc\u30c9 \u2014 multi-hop \u8a18\u61b6\u63a2\u7d22\u3092\u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u6f14\u51fa'));
    panel.appendChild(toggleLabel);
    if (anchor) tab.insertBefore(panel, anchor);
    else tab.appendChild(panel);

    /* 発火モード本体 */
    var root = _el('div', { id: 'graph-fire-root', style: 'display:none' });
    var bar = _el('div', { 'class': 'glass', style: 'padding:14px 16px;margin-bottom:12px' });
    var row = _el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' });
    var query = _el('input', {
        type: 'text', id: 'graph-fire-query', 'class': 'glass-input',
        placeholder: '\u691c\u7d22\u30af\u30a8\u30ea', 'aria-label': '\u691c\u7d22\u30af\u30a8\u30ea',
        style: 'flex:1;min-width:180px'
    });
    row.appendChild(query);
    var decLabel = _el('label', { style: 'display:flex;align-items:center;gap:6px;color:var(--text-secondary);font-size:0.85rem;cursor:pointer;user-select:none' });
    var decision = _el('input', { type: 'checkbox', id: 'graph-fire-decision', 'aria-label': 'decision' });
    decision.checked = true;
    decision.style.accentColor = 'var(--accent-purple)';
    decLabel.appendChild(decision);
    decLabel.appendChild(_el('span', null, 'decision'));
    row.appendChild(decLabel);
    /* turn モード: chat 由来の発火を turn_id で束ねる（手動 FIRE と共存）。 */
    var turnLabel = _el('label', { style: 'display:flex;align-items:center;gap:6px;color:var(--text-secondary);font-size:0.85rem;cursor:pointer;user-select:none' });
    var turnMode = _el('input', { type: 'checkbox', id: 'graph-fire-turn-mode', 'aria-label': 'turn' });
    turnMode.style.accentColor = 'var(--accent-pink)';
    turnLabel.appendChild(turnMode);
    turnLabel.appendChild(_el('span', null, 'turn'));
    row.appendChild(turnLabel);
    /* 1..5 に clamp する契約。select は範囲外の値を保持できず
       （value='9' が value='' に化ける）clamp が働かないので number 入力。 */
    var hops = _el('input', { type: 'number', id: 'graph-fire-hops', min: '1', max: '5', step: '1', value: String(FIRE_DEFAULT_HOPS), 'class': 'glass-input', 'aria-label': 'hops', title: '\u6700\u5927\u30db\u30c3\u30d7\u6570 (1-5)', style: 'min-width:70px' });
    row.appendChild(hops);
    row.appendChild(_el('button', { id: 'graph-fire-run', 'class': 'glass-btn', style: 'padding:6px 14px;font-size:0.82rem' }, '\u767a\u706b'));
    row.appendChild(_el('span', { id: 'graph-fire-status' }));
    bar.appendChild(row);
    root.appendChild(bar);

    root.appendChild(_el('div', { id: 'graph-fire-container', 'class': 'glass', style: 'height:600px;position:relative;overflow:hidden' }));

    var results = _el('div', { id: 'graph-fire-results', 'class': 'glass', style: 'padding:16px;margin-top:12px;display:none' });
    results.appendChild(_el('div', { style: 'font-size:0.85rem;font-weight:600;color:var(--text-primary);margin-bottom:8px' }, '\u7d50\u679c \u2014 \u5168 hop \u7d2f\u7a4d\u4e0a\u4f4d20\u4ef6'));
    results.appendChild(_el('ol', { id: 'graph-fire-results-list', style: 'list-style:none;margin:0;padding:0' }));
    root.appendChild(results);

    if (anchor && anchor.parentNode === tab) tab.insertBefore(root, anchor.nextSibling);
    else tab.appendChild(root);

    return {
        panel: panel, root: root, toggle: toggle, query: query,
        decision: decision, hops: hops, turnMode: turnMode,
        run: root.querySelector('#graph-fire-run'),
        status: root.querySelector('#graph-fire-status'),
        container: root.querySelector('#graph-fire-container'),
        results: results,
        resultsList: root.querySelector('#graph-fire-results-list')
    };
}

/* ---- 起動（パース時。タブが存在しない環境では何もしない） ---- */

(function setupFireMode() {
    var tab = document.getElementById('tab-graph');
    if (!tab || document.getElementById('graph-fire-toggle')) return;
    fireUI = buildFireUI(tab);
    fireUI.toggle.addEventListener('change', function () { setMode(this.checked); });
    fireUI.run.addEventListener('click', runFire);
    fireUI.turnMode.addEventListener('change', function () { setTurnMode(this.checked); });
    fireUI.query.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') runFire();
    });
})();

/* Namespace 登録 */
N.Features.GraphFire = {
    setMode: setMode,
    setTurnMode: setTurnMode,
    isMode: function () { return fireState.mode; },
    run: runFire,
    handleFireEvent: handleFireEvent,
    connectFireStream: connectFireStream,
    disconnectFireStream: disconnectFireStream,
    setFireDataSet: setFireDataSet,
    resetScene: resetFireScene,
    renderResults: renderResults,
    /* テストフック */
    _state: function () { return fireState; },
    _pulseNode: pulseNode,
    _excerpt: excerpt,
    _uuid: _uuid
};
})();
