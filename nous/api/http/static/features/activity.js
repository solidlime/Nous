/* =================================================================
   ACTIVITY TAB — Session event viewer
   Namespace: N.Features.Activity.*
   ================================================================= */
N.Features.Activity = N.Features.Activity || {};

;(function() {
var S = window.S;
var { esc, api, relativeTime, fmtDateTime, safeSetHTML } = window.Nous.Core;

/* =================================================================
   ACTIVITY TAB
   ================================================================= */
const ACT = {
    limit: 50,
    offset: 0,
    total: 0,
    filterType: '',
    filterOrder: 'desc',
    sessions: {}  // session_id -> { open: bool, events: [], platform }
};

// Tool-call timeline (kanban: ツール実行のタイムライン)
const TOOL_LIMIT = 100;
const TOOL_COLUMNS = ['Time', 'Tool', 'Duration', 'Exit', 'Command'];

const ACT_ICONS = {
    'tool.called':        '<i data-lucide="wrench"></i>',
    'chat.message':       '<i data-lucide="message-square"></i>',
    'chat.llm_response':  '<i data-lucide="bot"></i>',
    'session.started':    '<i data-lucide="play"></i>',
    'session.compact':    '<i data-lucide="shrink"></i>',
    'events.ingested':    '<i data-lucide="upload"></i>',
    'place.moved':        '<i data-lucide="map-pin"></i>',
};

const ACT_LABELS = {
    'tool.called':        'Tool',
    'chat.message':       'You',
    'chat.llm_response':  'AI',
    'session.started':    'Start',
    'session.compact':    'Compress',
    'events.ingested':    'External',
    'place.moved':        'Move',
};

const ACT_PLATFORM_ICONS = {
    'webui':    '<i data-lucide="globe"></i>',
    'opencode': '<i data-lucide="terminal"></i>',
    'mcp':      '<i data-lucide="plug"></i>',
    'plugin':   '<i data-lucide="puzzle"></i>',
};

async function loadMetrics() {
    const el = document.getElementById('act-metrics');
    if (!el || !S.persona) return;
    try {
        const m = await api('/api/metrics/' + encodeURIComponent(S.persona));
        const s = m.search || {};
        const w = m.wiki || {};
        const tools = Object.keys(m.tools || {}).length;
        const parts = [
            '検索 ' + (s.count || 0) + ' 回 / p50 ' + (s.p50_ms || 0) + 'ms / p95 ' + (s.p95_ms || 0) + 'ms',
            'zero-result ' + Math.round((s.zero_result_rate || 0) * 100) + '%',
            'ツール ' + tools + ' 種',
            '編纂 ' + ((w['wiki.compiled'] || 0)) + ' / 保存 ' + ((w['wiki.saved'] || 0)) + ' / 暮らし ' + ((w['wiki.life'] || 0))
        ];
        el.textContent = parts.join('　·　');
    } catch (e) {
        console.warn('metrics load failed:', e);
        el.textContent = '';
    }
}

/* tool.called 1件 → タイムラインの1行。取れない列は "—" にする。
   duration_ms / exit_code / command は metadata に載っている時だけ表示する
   (plugin ingest 由来のイベントが主。chat 側 registry 発行分は metadata を持たない)。 */
function buildToolRow(ev) {
    const md = (ev.metadata && typeof ev.metadata === 'object') ? ev.metadata : {};
    let tool = md.tool_name;
    if (!tool) {
        const m = String(ev.summary || '').match(/^\s*([A-Za-z0-9_.\-]+)\s*:/);
        tool = m ? m[1] : String(ev.summary || 'unknown');
    }
    const dur = md.duration_ms;
    const exit = md.exit_code;
    const cmd = md.command != null && md.command !== '' ? md.command : md.params_summary;
    const cmdLine = cmd == null || cmd === '' ? '—' : String(cmd).split('\n')[0].slice(0, 120);
    return {
        timestamp: ev.timestamp || '',
        time: fmtDateTime(ev.timestamp),
        tool: String(tool),
        duration: (dur === undefined || dur === null || dur === '') ? '—' : dur + ' ms',
        exit: (exit === undefined || exit === null || exit === '') ? '—' : String(exit),
        command: cmdLine,
    };
}

function buildToolTimelineHTML(events) {
    const rows = (events || [])              // 新しい順・上限 100 件
        .slice()
        .sort((a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || '')))
        .slice(0, TOOL_LIMIT)
        .map(buildToolRow);

    if (rows.length === 0) {
        return '<div class="act-empty">No tool calls recorded yet.</div>';
    }

    let html = '<div class="act-tool-wrap"><table class="act-tool-table"><thead><tr>';
    for (const col of TOOL_COLUMNS) html += '<th scope="col">' + esc(col) + '</th>';
    html += '</tr></thead><tbody>';
    for (const r of rows) {
        html += '<tr class="act-tool-row">';
        html += '<td class="act-tool-time">' + esc(r.time) + '</td>';
        html += '<td class="act-tool-name">' + esc(r.tool) + '</td>';
        html += '<td class="act-tool-duration">' + esc(r.duration) + '</td>';
        html += '<td class="act-tool-exit">' + esc(r.exit) + '</td>';
        html += '<td class="act-tool-command" title="' + esc(r.command) + '">' + esc(r.command) + '</td>';
        html += '</tr>';
    }
    return html + '</tbody></table></div>';
}

function renderToolTimeline(events) {
    const feed = document.getElementById('act-feed');
    if (!feed) return;
    safeSetHTML(feed, buildToolTimelineHTML(events));
}

async function loadActivity(reset = false) {
    if (reset) { ACT.offset = 0; ACT.sessions = {}; }

    loadMetrics();

    const feed = document.getElementById('act-feed');
    if (!feed) return;

    const typeEl = document.getElementById('act-filter-type');
    const orderEl = document.getElementById('act-filter-order');
    ACT.filterType = typeEl ? typeEl.value : '';
    ACT.filterOrder = orderEl ? orderEl.value : 'desc';

    const isToolTimeline = ACT.filterType === 'tool.called';
    let url = '/api/session-events/' + encodeURIComponent(S.persona) +
        '?limit=' + (isToolTimeline ? TOOL_LIMIT : ACT.limit) +
        '&offset=' + (isToolTimeline ? 0 : ACT.offset) +
        '&order=' + ACT.filterOrder;
    if (ACT.filterType) url += '&event_type=' + encodeURIComponent(ACT.filterType);

    try {
        const data = await api(url);
        ACT.total = data.total;
        const events = data.events || [];

        if (reset) {
            ACT.offset = 0;
            ACT.sessions = {};
            feed.textContent = '';
        }

        // Tool Calls は session 折り畳みではなくフラットな表で出す（100 件固定・ページング無し）
        if (isToolTimeline) {
            const old = document.getElementById('act-load-more');
            if (old) old.remove();
            renderToolTimeline(events);
            return;
        }

        if (events.length === 0 && ACT.offset === 0) {
            safeSetHTML(feed, N.Components.skeleton.emptyState('activity', 'Activity', 'No session activity recorded yet.'));
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        // Group events by session_id
        for (const ev of events) {
            const sid = ev.session_id;
            if (!ACT.sessions[sid]) {
                ACT.sessions[sid] = {
                    open: Object.keys(ACT.sessions).length === 0 && ACT.offset === 0,
                    events: [],
                    platform: (ev.metadata && ev.metadata.platform) || 'webui',
                };
            }
            ACT.sessions[sid].events.push(ev);
        }

        renderActivityFeed();
        ACT.offset += events.length;

        // Load more button
        const hasMore = data.has_more;
        let loadMoreEl = document.getElementById('act-load-more');
        if (hasMore) {
            if (!loadMoreEl) {
                loadMoreEl = document.createElement('button');
                loadMoreEl.id = 'act-load-more';
                loadMoreEl.className = 'act-load-more';
                loadMoreEl.textContent = 'Load more...';
                loadMoreEl.addEventListener('click', function () { loadActivity(false); });
                feed.appendChild(loadMoreEl);
            }
        } else if (loadMoreEl) {
            loadMoreEl.remove();
        }

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        console.error('activity load failed:', e);
        safeSetHTML(feed, N.Components.skeleton.errorCard('Failed to load activity', function(){ loadActivity(true); }));
    }
}
/* N.Features.Activity.loadActivity registered below */

function renderActivityFeed() {
    const feed = document.getElementById('act-feed');
    if (!feed) return;
    // Remove old load-more button before re-rendering
    const oldBtn = document.getElementById('act-load-more');
    if (oldBtn) oldBtn.remove();

    let html = '';

    // Iterate sessions in current display order
    const sessionIds = Object.keys(ACT.sessions);
    // Sort by first event timestamp
    sessionIds.sort((a, b) => {
        const ta = ACT.sessions[a].events[0]?.timestamp || '';
        const tb = ACT.sessions[b].events[0]?.timestamp || '';
        return ACT.filterOrder === 'desc' ? tb.localeCompare(ta) : ta.localeCompare(tb);
    });

    for (const sid of sessionIds) {
        const sess = ACT.sessions[sid];
        const platformIcon = ACT_PLATFORM_ICONS[sess.platform] || '';
        const firstTs = sess.events[0]?.timestamp || '';
        const eventCount = sess.events.length;
        const openClass = sess.open ? ' open' : '';

        html += '<div class="act-session' + openClass + '" data-session="' + esc(sid) + '">';
        html += '<div class="act-session-header" tabindex="0" role="button" data-act-session="' + esc(sid) + '">';
        html += '<span class="act-chevron">▶</span>';
        html += '<span class="act-session-id">' + esc(sid) + '</span>';
        html += '<span class="act-session-meta">';
        if (platformIcon) html += '<span class="act-platform-badge">' + platformIcon + ' ' + esc(sess.platform) + '</span>';
        html += '<span>' + eventCount + ' event' + (eventCount !== 1 ? 's' : '') + '</span>';
        html += '<span>' + relativeTime(firstTs) + '</span>';
        html += '</span></div>';

        html += '<div class="act-session-body">';
        // Sort events within session by timestamp
        const sorted = [...sess.events];
        sorted.sort((a, b) => {
            return ACT.filterOrder === 'desc'
                ? b.timestamp.localeCompare(a.timestamp)
                : a.timestamp.localeCompare(b.timestamp);
        });
        for (const ev of sorted) {
            const icon = ACT_ICONS[ev.event_type] || '<i data-lucide="circle"></i>';
            const label = ACT_LABELS[ev.event_type] || ev.event_type;
            const hasDetail = ev.detail && ev.detail.length > 0;
            html += '<div class="act-event type-' + esc(ev.event_type) + '"';
            if (hasDetail) html += ' data-act-detail="1" tabindex="0" role="button"';
            html += '>';
            html += '<span class="act-event-icon">' + icon + '</span>';
            html += '<div class="act-event-body">';
            html += '<div class="act-event-summary"><span>' + esc(label) + '</span> ' + esc(ev.summary) + '</div>';
            html += '<div class="act-event-time">' + fmtDateTime(ev.timestamp) + '</div>';
            if (hasDetail) {
                html += '<div class="act-event-detail">' + esc(ev.detail) + '</div>';
            }
            html += '</div></div>';
        }
        html += '</div></div>';
    }

    safeSetHTML(feed, html);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleActivitySession(sid) {
    if (!sid) return;
    const sessionEl = document.querySelector('.act-session[data-session="' + CSS.escape(sid) + '"]');
    if (!sessionEl) return;
    ACT.sessions[sid].open = !ACT.sessions[sid].open;
    if (ACT.sessions[sid].open) {
        sessionEl.classList.add('open');
        // Update chevron
        const body = sessionEl.querySelector('.act-session-body');
        if (body && (body.textContent || '').trim() === '') {
            // Lazy render events
            const sess = ACT.sessions[sid];
            const sorted = [...sess.events];
            sorted.sort((a, b) => ACT.filterOrder === 'desc'
                ? b.timestamp.localeCompare(a.timestamp)
                : a.timestamp.localeCompare(b.timestamp));
            let h = '';
            for (const ev of sorted) {
                const icon = ACT_ICONS[ev.event_type] || '<i data-lucide="circle"></i>';
                const label = ACT_LABELS[ev.event_type] || ev.event_type;
                const hasDetail = ev.detail && ev.detail.length > 0;
                h += '<div class="act-event type-' + esc(ev.event_type) + '"';
                if (hasDetail) h += ' data-act-detail="1" tabindex="0" role="button"';
                h += '>';
                h += '<span class="act-event-icon">' + icon + '</span>';
                h += '<div class="act-event-body">';
                h += '<div class="act-event-summary"><span>' + esc(label) + '</span> ' + esc(ev.summary) + '</div>';
                h += '<div class="act-event-time">' + fmtDateTime(ev.timestamp) + '</div>';
                if (hasDetail) h += '<div class="act-event-detail">' + esc(ev.detail) + '</div>';
                h += '</div></div>';
            }
            safeSetHTML(body, h);
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } else {
        sessionEl.classList.remove('open');
    }
}
/* N.Features.Activity.toggleActivitySession registered below */

function toggleActivityDetail(el) {
    el.classList.toggle('expanded');
}
/* N.Features.Activity.toggleActivityDetail registered below */

// Keyboard: Enter/Space on session headers and event detail toggles
// Click delegation (CSP-safe: no inline onclick)
document.addEventListener("click", function(e) {
    var sessHeader = e.target && e.target.closest ? e.target.closest("[data-act-session]") : null;
    if (sessHeader) {
        toggleActivitySession(sessHeader.getAttribute("data-act-session"));
        return;
    }
    var detail = e.target && e.target.closest ? e.target.closest("[data-act-detail]") : null;
    if (detail) {
        toggleActivityDetail(detail);
    }
});
document.addEventListener("keydown", function(e) {
    if (e.key === "Enter" || e.key === " ") {
        var target = e.target.closest(".act-session-header, .act-event[data-act-detail]");
        if (target) {
            e.preventDefault();
            target.click();
        }
    }
});

// Register in namespace
Object.assign(N.Features.Activity, {
    loadActivity: loadActivity,
    loadMetrics: loadMetrics,
    toggleActivitySession: toggleActivitySession,
    toggleActivityDetail: toggleActivityDetail,
    renderActivityFeed: renderActivityFeed,
    buildToolRow: buildToolRow,
    buildToolTimelineHTML: buildToolTimelineHTML,
    renderToolTimeline: renderToolTimeline,
});
})();
