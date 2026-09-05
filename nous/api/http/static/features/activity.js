/* =================================================================
   ACTIVITY TAB — Session event viewer
   Namespace: N.Features.Activity.*
   ================================================================= */
N.Features.Activity = N.Features.Activity || {};

;(function() {
var S = window.S;
var { esc, api, relativeTime, safeSetHTML } = window.Nous.Core;

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

const ACT_ICONS = {
    'tool.called':        '<i data-lucide="wrench"></i>',
    'chat.message':       '<i data-lucide="message-square"></i>',
    'chat.llm_response':  '<i data-lucide="bot"></i>',
    'session.started':    '<i data-lucide="play"></i>',
    'session.compact':    '<i data-lucide="shrink"></i>',
    'events.ingested':    '<i data-lucide="upload"></i>',
};

const ACT_LABELS = {
    'tool.called':        'Tool',
    'chat.message':       'You',
    'chat.llm_response':  'AI',
    'session.started':    'Start',
    'session.compact':    'Compress',
    'events.ingested':    'External',
};

const ACT_PLATFORM_ICONS = {
    'webui':    '<i data-lucide="globe"></i>',
    'opencode': '<i data-lucide="terminal"></i>',
    'mcp':      '<i data-lucide="plug"></i>',
    'plugin':   '<i data-lucide="puzzle"></i>',
};

async function loadActivity(reset = false) {
    if (reset) { ACT.offset = 0; ACT.sessions = {}; }

    const feed = document.getElementById('act-feed');
    if (!feed) return;

    const typeEl = document.getElementById('act-filter-type');
    const orderEl = document.getElementById('act-filter-order');
    ACT.filterType = typeEl ? typeEl.value : '';
    ACT.filterOrder = orderEl ? orderEl.value : 'desc';

    let url = '/api/session-events/' + encodeURIComponent(S.persona) +
        '?limit=' + ACT.limit + '&offset=' + ACT.offset + '&order=' + ACT.filterOrder;
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
            html += '<div class="act-event-time">' + new Date(ev.timestamp).toLocaleString('ja-JP') + '</div>';
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
                h += '<div class="act-event-time">' + new Date(ev.timestamp).toLocaleString('ja-JP') + '</div>';
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
    toggleActivitySession: toggleActivitySession,
    toggleActivityDetail: toggleActivityDetail,
    renderActivityFeed: renderActivityFeed,
});
})();
