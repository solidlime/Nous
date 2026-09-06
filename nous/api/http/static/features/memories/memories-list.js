/* =================================================================
   MEMORIES LIST — List rendering, view modes, pagination
   Namespace: N.Features.Memories.*
   Depends on: N.Core.* (esc, truncate, relativeTime)
               N.Features.Memories.* (tagChipHtml, loadMemories)
               window.S, window.safeSetHTML, window.lucide, window.renderBodyStateCompact,
               window.renderEmotionBadges, window.switchTab
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;
var { esc, truncate, relativeTime, safeSetHTML } = window.Nous.Core;

/* ================================================================
   renderMemoryList
   ================================================================ */
function renderMemoryList(el, memories, tagOptions, totalPages, totalCount, isSearch, allKnownTags) {
    var selMode = S.mem.selectMode;
    var cbClass = selMode ? 'mem-cb show' : 'mem-cb';
    allKnownTags = allKnownTags || [];

    /* ── Search bar ── */
    var html = '<div class="glass p-4 mb-6">';
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">';
    html += '<input id="mem-search" type="text" class="glass-input" style="flex:1;min-width:200px" placeholder="Search memories..." value="' + esc(S.mem.q) + '">';
    html += '<select id="mem-tag" class="glass-input">' + tagOptions + '</select>';
    html += '<button id="mem-search-btn" class="glass-btn"><i data-lucide="search"></i> Search</button>';
    html += '<button id="adv-search-toggle" class="glass-btn" style="font-size:0.8rem"><i data-lucide="search"></i> Advanced</button>';
    html += '</div>';

    /* ── Advanced search panel ── */
    html += '<div id="adv-search-panel" class="adv-search-panel' + (S.mem.advOpen ? ' open' : '') + '">';

    /* Search mode */
    html += '<div class="adv-search-row" style="margin-top:8px">';
    html += '<span class="adv-search-label">Mode</span>';
    html += '<div class="mode-btn-group">';
    var modes = ['semantic','keyword','hybrid','smart'];
    for (var mi = 0; mi < modes.length; mi++) {
        var m = modes[mi];
        html += '<button class="mode-btn adv-mode-btn' + (S.mem.searchMode === m ? ' active' : '') + '" data-mode="' + m + '">' + m + '</button>';
    }
    html += '</div></div>';

    /* Date range */
    html += '<div class="adv-search-row">';
    html += '<span class="adv-search-label">Date From</span>';
    html += '<input type="date" id="adv-date-from" class="glass-input" style="font-size:0.8rem" value="' + esc(S.mem.dateFrom) + '">';
    html += '<span class="adv-search-label" style="min-width:auto">To</span>';
    html += '<input type="date" id="adv-date-to" class="glass-input" style="font-size:0.8rem" value="' + esc(S.mem.dateTo) + '">';
    html += '</div>';

    /* Importance range */
    html += '<div class="adv-search-row">';
    html += '<span class="adv-search-label">Importance</span>';
    html += '<span class="range-value" id="adv-imp-min-val">' + S.mem.impMin.toFixed(2) + '</span>';
    html += '<input type="range" class="glass-range" id="adv-imp-min" min="0" max="1" step="0.01" value="' + S.mem.impMin + '" style="max-width:140px">';
    html += '<span style="color:var(--text-muted);font-size:0.75rem">~</span>';
    html += '<input type="range" class="glass-range" id="adv-imp-max" min="0" max="1" step="0.01" value="' + S.mem.impMax + '" style="max-width:140px">';
    html += '<span class="range-value" id="adv-imp-max-val">' + S.mem.impMax.toFixed(2) + '</span>';
    html += '</div>';

    /* Tags filter pills */
    html += '<div class="adv-search-row">';
    html += '<span class="adv-search-label">Tags</span>';
    html += '<div class="filter-tags-wrap" id="adv-tags-wrap">';
    for (var ti = 0; ti < allKnownTags.length; ti++) {
        var t = allKnownTags[ti];
        var isActive = S.mem.searchTags.indexOf(t) !== -1;
        html += '<span class="filter-tag adv-filter-tag' + (isActive ? ' active' : '') + '" data-tag="' + esc(t) + '">' + esc(t) + '</span>';
    }
    if (allKnownTags.length === 0) html += '<span style="font-size:0.75rem;color:var(--text-muted)">No tags available</span>';
    html += '</div></div>';

    /* Emotion filter */
    html += '<div class="adv-search-row">';
    html += '<span class="adv-search-label">Emotion</span>';
    html += '<select id="adv-emotion" class="glass-input" style="font-size:0.8rem">';
    html += '<option value="">Any</option>';
    var emos = Object.keys(N.Core.EMOTION_COLORS).sort();
    for (var ei = 0; ei < emos.length; ei++) {
        html += '<option value="' + emos[ei] + '"' + (S.mem.emotion === emos[ei] ? ' selected' : '') + '>' + emos[ei] + '</option>';
    }
    html += '</select></div>';

    /* Apply / Clear buttons */
    html += '<div class="adv-search-row" style="justify-content:flex-end;margin-top:4px">';
    html += '<button id="adv-clear-btn" class="glass-btn" style="font-size:0.78rem">Clear</button>';
    html += '<button id="adv-apply-btn" class="glass-btn glass-btn-success" style="font-size:0.78rem">Apply Filters</button>';
    html += '</div>';

    html += '</div>'; /* close adv-search-panel */
    html += '</div>'; /* close glass */

    /* ── Toolbar row ── */
    html += '<div class="mem-toolbar">';
    html += '<button id="mem-new-btn" class="glass-btn glass-btn-success" style="font-size:0.82rem">&#10133; New Memory</button>';
    html += '<button id="mem-select-toggle" class="glass-btn" style="font-size:0.82rem">' + (selMode ? '&#9745; Select ON' : '&#9744; Select') + '</button>';
    html += '<div class="mem-toolbar-spacer"></div>';
    html += '<select id="mem-sort" class="glass-input mem-sort-select">';
    var sortOpts = [['date_desc','Newest First'],['date_asc','Oldest First'],['imp_desc','Importance <i data-lucide="arrow-down"></i>'],['str_desc','Strength <i data-lucide="arrow-down"></i>'],['updated_desc','Recently Updated']];
    for (var si = 0; si < sortOpts.length; si++) {
        html += '<option value="' + sortOpts[si][0] + '"' + (S.mem.sort === sortOpts[si][0] ? ' selected' : '') + '>' + sortOpts[si][1] + '</option>';
    }
    html += '</select>';
    html += '<div class="view-toggle">';
    html += '<button class="view-btn' + (S.mem.viewMode === 'card' ? ' active' : '') + '" data-view="card">&#9638; Cards</button>';
    html += '<button class="view-btn' + (S.mem.viewMode === 'compact' ? ' active' : '') + '" data-view="compact">&#9776; Compact</button>';
    html += '</div>';
    html += '</div>';

    /* ── Batch bar ── */
    html += '<div id="mem-batch-bar" class="mem-batch-bar' + (selMode ? ' active' : '') + '">';
    html += '<button id="batch-select-all" class="glass-btn" style="font-size:0.78rem">Select All</button>';
    html += '<button id="batch-deselect" class="glass-btn" style="font-size:0.78rem">Deselect All</button>';
    html += '<div class="mem-toolbar-spacer"></div>';
    html += '<button id="batch-delete" class="glass-btn glass-btn-danger" style="font-size:0.78rem"><i data-lucide="trash-2"></i> Delete Selected (<span id="batch-count">' + S.mem.selected.size + '</span>)</button>';
    html += '</div>';

    /* ── Memory items ── */
    html += '<div id="mem-list" class="glass" style="overflow:hidden">';
    if (memories.length === 0) {
        html += '<div class="empty-state">' +
            '<div class="empty-state-icon"><i data-lucide="brain"></i></div>' +
            '<div class="empty-state-text">まだ記憶がありません。<br>Chatタブで「記憶して」と話しかけてみてください。</div>' +
            '<button class="empty-state-cta" data-tab="chat"><i data-lucide="message-circle"></i> Chatを開く</button>' +
            '</div>';
    } else if (S.mem.viewMode === 'compact') {
        /* ── Compact view ── */
        memories.forEach(function(m) {
            var key = m.memory_key || m.key || '';
            var checked = S.mem.selected.has(key) ? ' checked' : '';
            var tags = (m.context_tags || m.tags || []);
            var tagsHtml = tags.slice(0, 3).map(function(t){ return N.Features.Memories.tagChipHtml(t); }).join(' ');
            var impPct = m.importance != null ? (m.importance * 100) : 0;
            var timeStr = m.created_at ? relativeTime(m.created_at) : '';
            var bodyCompactHtml = N.Components.memoryCard.renderBodyStateCompact(m.body_state);
            var emotionCompactHtml = N.Components.memoryCard.renderEmotionBadges(m.emotion, m.emotion_intensity);

            html += '<div class=\"memory-compact\" data-memkey=\"' + esc(key) + '\">';
            html += '<span class=\"' + cbClass + '\"><input type=\"checkbox\" class=\"mem-checkbox\" data-key=\"' + esc(key) + '\"' + checked + '></span>';
            html += '<span class=\"mem-compact-key\">' + esc(truncate(key, 20)) + '</span>';
            html += '<span class=\"mem-compact-content\">' + esc(truncate(m.content || '', 80)) + '</span>';
            html += '<span class=\"mem-compact-meta\">' + tagsHtml + '</span>';
            html += '<span class="mem-compact-meta"><span class="mem-compact-imp"><span class="mem-compact-imp-fill" style="width:' + impPct + '%"></span></span></span>';
            html += '<span class=\"mem-compact-meta\" style=\"font-size:0.72rem;color:var(--text-muted);min-width:50px\">' + emotionCompactHtml + ' ' + bodyCompactHtml + ' ' + timeStr + '</span>';
            html += '</div>';
        });
    } else {
        /* ── Card view ── */
        memories.forEach(function(m) {
            var key = m.memory_key || m.key || '';
            var checked = S.mem.selected.has(key) ? ' checked' : '';
            var tags = (m.context_tags || m.tags || []);
            var tagsHtml = tags.map(function(t){ return N.Features.Memories.tagChipHtml(t); }).join(' ');
            var emoColor = N.Core.EMOTION_COLORS[m.emotion] || '#94a3b8';
            var emoHtml = m.emotion ? '<span class=\"badge\" style=\"background:' + emoColor + '22;color:' + emoColor + ';border:1px solid ' + emoColor + '44\">' + esc(m.emotion) + (m.emotion_intensity != null ? '(' + m.emotion_intensity.toFixed(1) + ')' : '') + '</span>' : '';
            var emotionBadgesHtml = N.Components.memoryCard.renderEmotionBadges(m.emotion, m.emotion_intensity);
            var strHtml = m.strength != null ? '<span style=\"color:var(--accent-yellow)\"><i data-lucide="zap"></i>' + m.strength.toFixed(2) + '</span>' : '';
            var timeHtml = m.created_at ? '<span>\uD83D\uDCC5 ' + relativeTime(m.created_at) + '</span>' : '';
            var scoreHtml = m._score != null ? '<span class=\"badge badge-green\">Score: ' + m._score.toFixed(3) + '</span>' : '';
            var bodyCardHtml = N.Components.memoryCard.renderBodyStateCompact(m.body_state);
            html += '<div class="memory-card" style="cursor:pointer" data-memkey="' + esc(key) + '">';
            html += '<div style=\"display:flex;align-items:center;gap:8px\">';
            html += '<span class=\"' + cbClass + '\"><input type=\"checkbox\" class=\"mem-checkbox\" data-key=\"' + esc(key) + '\"' + checked + '></span>';
            html += '<div class=\"memory-key\">' + esc(key) + '</div>';
            html += '</div>';
            html += '<div class=\"memory-content\">' + esc(truncate(m.content || '', 200)) + '</div>';
            html += '<div class=\"memory-meta\">' + tagsHtml + ' ' + emoHtml + ' ' + emotionBadgesHtml + ' ' + strHtml + ' ' + scoreHtml + ' ' + bodyCardHtml + ' ' + timeHtml + '</div>';
            html += '</div>';
        });
    }
    html += '</div>'; /* close mem-list */

    /* ── Pagination ── */
    if (!isSearch && totalPages > 0) {
        html += '<div style="display:flex;justify-content:center;align-items:center;gap:12px;margin-top:16px">';
        html += '<button class="glass-btn mem-page-btn" data-page="' + (S.mem.page - 1) + '"' + (S.mem.page <= 1 ? ' disabled style="opacity:0.4;pointer-events:none"' : '') + '><i data-lucide="chevron-left"></i> Prev</button>';
        html += '<span style="font-size:0.85rem;color:var(--text-muted)">Page ' + S.mem.page + ' of ' + totalPages + ' (' + totalCount + ' total)</span>';
        html += '<button class="glass-btn mem-page-btn" data-page="' + (S.mem.page + 1) + '"' + (S.mem.page >= totalPages ? ' disabled style="opacity:0.4;pointer-events:none"' : '') + '>Next <i data-lucide="chevron-right"></i></button>';
        html += '</div>';
    }
    safeSetHTML(el, html);
    if (N.Components.memoryCard) N.Components.memoryCard.applyDataStyles(el);
}

/* ================================================================
   toggleSelectMode
   ================================================================ */
function toggleSelectMode() {
    S.mem.selectMode = !S.mem.selectMode;
    if (!S.mem.selectMode) S.mem.selected.clear();
    N.Features.Memories.loadMemories();
}

Object.assign(N.Features.Memories, {
    renderMemoryList: renderMemoryList,
    toggleSelectMode: toggleSelectMode,
});
})();
