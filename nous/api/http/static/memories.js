;(function() {
var S = window.S;
/* =================================================================
   MEMORIES TAB — Extended State + Full CRUD
   ================================================================= */
var { esc, toast, api, truncate, relativeTime, showConfirm } = window.Nous.Core;
if (S && S.mem) Object.assign(S.mem, {
    sort: 'date_desc', viewMode: 'compact', selectMode: false, selected: new Set(),
    searchMode: 'hybrid', dateFrom: '', dateTo: '', impMin: 0, impMax: 1,
    searchTags: [], emotion: '', advOpen: false
});

/* ── Hash to hue ── */
function hashToHue(str) {
    var h = 0;
    for (var i = 0; i < str.length; i++) { h = str.charCodeAt(i) + ((h << 5) - h); }
    return Math.abs(h) % 360;
}

/* ── Tag chip HTML ── */
function tagChipHtml(tag) {
    var hue = hashToHue(tag);
    return '<span class="mem-tag-chip" style="--chip-hue:' + hue + '">' + esc(tag) + '</span>';
}

/* ── Client-side sort helper ── */
function _sortMemories(arr) {
    var s = S.mem.sort;
    var sorted = arr.slice();
    if (s === 'date_desc') sorted.sort(function(a,b){ return (b.created_at||'').localeCompare(a.created_at||''); });
    else if (s === 'date_asc') sorted.sort(function(a,b){ return (a.created_at||'').localeCompare(b.created_at||''); });
    else if (s === 'imp_desc') sorted.sort(function(a,b){ return (b.importance||0) - (a.importance||0); });
    else if (s === 'str_desc') sorted.sort(function(a,b){ return (b.strength||0) - (a.strength||0); });
    else if (s === 'updated_desc') sorted.sort(function(a,b){ return (b.updated_at||'').localeCompare(a.updated_at||''); });
    return sorted;
}

/* ── Client-side filter helper ── */
function _filterMemories(arr) {
    return arr.filter(function(m) {
        if (S.mem.dateFrom) {
            var d = m.created_at ? m.created_at.slice(0,10) : '';
            if (d < S.mem.dateFrom) return false;
        }
        if (S.mem.dateTo) {
            var d2 = m.created_at ? m.created_at.slice(0,10) : '';
            if (d2 > S.mem.dateTo) return false;
        }
        var imp = m.importance != null ? m.importance : 0;
        if (imp < S.mem.impMin || imp > S.mem.impMax) return false;
        if (S.mem.searchTags.length > 0) {
            var mtags = m.context_tags || m.tags || [];
            var hasTag = false;
            for (var i = 0; i < S.mem.searchTags.length; i++) {
                if (mtags.indexOf(S.mem.searchTags[i]) !== -1) { hasTag = true; break; }
            }
            if (!hasTag) return false;
        }
        if (S.mem.emotion && m.emotion !== S.mem.emotion) return false;
        return true;
    });
}

/* ================================================================
   loadMemories
   ================================================================ */
async function loadMemories(page) {
    if (page != null) S.mem.page = page;
    var el = document.getElementById('memories-content');

    /* Build tag dropdown options from cache */
    var tagOptions = '<option value="">All Tags</option>';
    var allKnownTags = [];
    if (S.dashCache && S.dashCache.stats && S.dashCache.stats.tag_distribution) {
        Object.keys(S.dashCache.stats.tag_distribution).sort().forEach(function(t) {
            tagOptions += '<option value="' + esc(t) + '"' + (S.mem.tag === t ? ' selected' : '') + '>' + esc(t) + '</option>';
            allKnownTags.push(t);
        });
    }

    try {
        var data, memories, totalPages = 0, totalCount = 0, isSearch = false;
        if (S.mem.q) {
            isSearch = true;
            var searchUrl = '/api/search/' + encodeURIComponent(S.persona)
                + '?q=' + encodeURIComponent(S.mem.q)
                + '&limit=50'
                + '&mode=' + encodeURIComponent(S.mem.searchMode);
            data = await api(searchUrl);
            var results = data.results || [];
            memories = results.map(function(r) {
                var m = Object.assign({}, r.memory || {});
                m._score = r.score; m._source = r.source;
                return m;
            });
            memories = _filterMemories(memories);
            memories = _sortMemories(memories);
        } else {
            var url = '/api/observations/' + encodeURIComponent(S.persona)
                + '?page=' + S.mem.page
                + '&per_page=' + S.mem.perPage
                + '&sort=desc';
            if (S.mem.tag) url += '&tag=' + encodeURIComponent(S.mem.tag);
            data = await api(url);
            memories = data.memories || [];
            memories = _filterMemories(memories);
            memories = _sortMemories(memories);
            totalPages = data.total_pages || 1;
            totalCount = data.total_count || 0;
        }
        renderMemoryList(el, memories, tagOptions, totalPages, totalCount, isSearch, allKnownTags);
        bindMemoryEvents();
        updateLastTime();
    } catch (e) {
        el.innerHTML = errorCard('Failed to load memories: ' + e.message);
    }
}

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
    var emos = ['joy','sadness','anger','fear','surprise','disgust','love','neutral','anticipation','trust','anxiety','excitement','frustration','nostalgia','pride','shame','guilt','loneliness','contentment','curiosity','awe','relief'];
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
            '<button class="empty-state-cta" onclick="switchTab(\'chat\')"><i data-lucide="message-circle"></i> Chatを開く</button>' +
            '</div>';
    } else if (S.mem.viewMode === 'compact') {
        /* ── Compact view ── */
        memories.forEach(function(m) {
            var key = m.memory_key || m.key || '';
            var checked = S.mem.selected.has(key) ? ' checked' : '';
            var tags = (m.context_tags || m.tags || []);
            var tagsHtml = tags.slice(0, 3).map(function(t){ return tagChipHtml(t); }).join(' ');
            var impPct = m.importance != null ? (m.importance * 100) : 0;
            var timeStr = m.created_at ? relativeTime(m.created_at) : '';
            /* Compact body state + emotion badges */
            var bodyCompactHtml = renderBodyStateCompact(m.body_state);
            var emotionCompactHtml = renderEmotionBadges(m.emotion, m.emotion_intensity);

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
            var tagsHtml = tags.map(function(t){ return tagChipHtml(t); }).join(' ');
            var emoColor = window.EMOTION_COLORS[m.emotion] || '#94a3b8';
            var emoHtml = m.emotion ? '<span class=\"badge\" style=\"background:' + emoColor + '22;color:' + emoColor + ';border:1px solid ' + emoColor + '44\">' + esc(m.emotion) + (m.emotion_intensity != null ? '(' + m.emotion_intensity.toFixed(1) + ')' : '') + '</span>' : '';
            var emotionBadgesHtml = renderEmotionBadges(m.emotion, m.emotion_intensity);
            var strHtml = m.strength != null ? '<span style=\"color:var(--accent-yellow)\"><i data-lucide="zap"></i>' + m.strength.toFixed(2) + '</span>' : '';
            var timeHtml = m.created_at ? '<span>\uD83D\uDCC5 ' + relativeTime(m.created_at) + '</span>' : '';
            var scoreHtml = m._score != null ? '<span class=\"badge badge-green\">Score: ' + m._score.toFixed(3) + '</span>' : '';
            /* Compact body state for card view */
            var bodyCardHtml = renderBodyStateCompact(m.body_state);
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
    el.innerHTML = html;
}
window.loadMemories = loadMemories;

/* ================================================================
   bindMemoryEvents
   ================================================================ */
function bindMemoryEvents() {
    var searchBtn = document.getElementById('mem-search-btn');
    var searchInput = document.getElementById('mem-search');
    var tagSelect = document.getElementById('mem-tag');

    /* Search button */
    if (searchBtn) searchBtn.onclick = function() {
        S.mem.q = searchInput ? searchInput.value.trim() : '';
        S.mem.tag = tagSelect ? tagSelect.value : '';
        S.mem.page = 1;
        loadMemories();
    };
    /* Enter in search */
    if (searchInput) searchInput.onkeydown = function(e) {
        if (e.key === 'Enter' && searchBtn) searchBtn.click();
    };
    /* Tag dropdown */
    if (tagSelect) tagSelect.onchange = function() {
        S.mem.tag = tagSelect.value;
        S.mem.q = '';
        if (searchInput) searchInput.value = '';
        S.mem.page = 1;
        loadMemories();
    };

    /* Page buttons */
    document.querySelectorAll('.mem-page-btn').forEach(function(btn) {
        btn.onclick = function() { loadMemories(parseInt(btn.dataset.page)); };
    });

    /* Memory card / compact row clicks */
    document.querySelectorAll('[data-memkey]').forEach(function(card) {
        card.onclick = function(e) {
            /* Don't open modal when clicking checkbox */
            if (e.target.type === 'checkbox') return;
            var key = card.getAttribute('data-memkey');
            if (!key) return;
            openMemModalByKey(key);
        };
    });

    /* New Memory button */
    var newBtn = document.getElementById('mem-new-btn');
    if (newBtn) newBtn.onclick = function() { openCreateModal(); };

    /* Select toggle */
    var selToggle = document.getElementById('mem-select-toggle');
    if (selToggle) selToggle.onclick = function() { toggleSelectMode(); };

    /* Sort dropdown */
    var sortSel = document.getElementById('mem-sort');
    if (sortSel) sortSel.onchange = function() {
        S.mem.sort = sortSel.value;
        loadMemories();
    };

    /* View toggle */
    document.querySelectorAll('.view-btn').forEach(function(btn) {
        btn.onclick = function() {
            S.mem.viewMode = btn.dataset.view;
            loadMemories();
        };
    });

    /* Advanced search toggle */
    var advToggle = document.getElementById('adv-search-toggle');
    if (advToggle) advToggle.onclick = function() { toggleAdvancedSearch(); };

    /* Checkboxes */
    document.querySelectorAll('.mem-checkbox').forEach(function(cb) {
        cb.onchange = function() {
            var k = cb.dataset.key;
            if (cb.checked) S.mem.selected.add(k);
            else S.mem.selected.delete(k);
            var countEl = document.getElementById('batch-count');
            if (countEl) countEl.textContent = S.mem.selected.size;
        };
    });

    /* Batch bar buttons */
    var batchAll = document.getElementById('batch-select-all');
    if (batchAll) batchAll.onclick = function() {
        document.querySelectorAll('.mem-checkbox').forEach(function(cb) {
            cb.checked = true;
            S.mem.selected.add(cb.dataset.key);
        });
        var countEl = document.getElementById('batch-count');
        if (countEl) countEl.textContent = S.mem.selected.size;
    };
    var batchDesel = document.getElementById('batch-deselect');
    if (batchDesel) batchDesel.onclick = function() {
        document.querySelectorAll('.mem-checkbox').forEach(function(cb) { cb.checked = false; });
        S.mem.selected.clear();
        var countEl = document.getElementById('batch-count');
        if (countEl) countEl.textContent = '0';
    };
    var batchDel = document.getElementById('batch-delete');
    if (batchDel) batchDel.onclick = function() { batchDeleteMemories(); };

    /* Advanced search: mode buttons */
    document.querySelectorAll('.adv-mode-btn').forEach(function(btn) {
        btn.onclick = function() {
            document.querySelectorAll('.adv-mode-btn').forEach(function(b){ b.classList.remove('active'); });
            btn.classList.add('active');
            S.mem.searchMode = btn.dataset.mode;
        };
    });

    /* Advanced search: importance sliders live update */
    var impMinSlider = document.getElementById('adv-imp-min');
    var impMaxSlider = document.getElementById('adv-imp-max');
    if (impMinSlider) impMinSlider.oninput = function() {
        var v = document.getElementById('adv-imp-min-val');
        if (v) v.textContent = parseFloat(impMinSlider.value).toFixed(2);
    };
    if (impMaxSlider) impMaxSlider.oninput = function() {
        var v = document.getElementById('adv-imp-max-val');
        if (v) v.textContent = parseFloat(impMaxSlider.value).toFixed(2);
    };

    /* Advanced search: filter tag pills toggle */
    document.querySelectorAll('.adv-filter-tag').forEach(function(pill) {
        pill.onclick = function() { pill.classList.toggle('active'); };
    });

    /* Advanced search: Apply */
    var advApply = document.getElementById('adv-apply-btn');
    if (advApply) advApply.onclick = function() { applyAdvancedSearch(); };

    /* Advanced search: Clear */
    var advClear = document.getElementById('adv-clear-btn');
    if (advClear) advClear.onclick = function() { clearAdvancedSearch(); };

    /* Edit modal: importance slider live update */
    var editImp = document.getElementById('edit-importance');
    if (editImp) editImp.oninput = function() {
        var v = document.getElementById('edit-imp-val');
        if (v) v.textContent = parseFloat(editImp.value).toFixed(2);
    };
    /* Edit modal: emotion intensity slider live update */
    var editEmo = document.getElementById('edit-emo-intensity');
    if (editEmo) editEmo.oninput = function() {
        var v = document.getElementById('edit-emo-val');
        if (v) v.textContent = parseFloat(editEmo.value).toFixed(2);
    };
    /* Edit modal: tag input Enter to add */
    var tagInput = document.getElementById('edit-tag-input');
    if (tagInput) tagInput.onkeydown = function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            var val = tagInput.value.trim();
            if (!val) return;
            _addEditTag(val);
            tagInput.value = '';
        }
    };
}

/* ================================================================
   openMemModalByKey — Fetch memory by key and open modal
   ================================================================ */
async function openMemModalByKey(key) {
    try {
        var data = await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key));
        if (data.memory) {
            openMemModal(data.memory);
        } else {
            toast('Memory not found', 'error');
        }
    } catch (e) {
        toast('Failed to load memory: ' + e.message, 'error');
    }
}

/* ================================================================
   openMemModal — OVERRIDE base.py version
   ================================================================ */
function openMemModal(mem) {
    var overlay = document.getElementById('mem-modal-overlay');
    var content = document.getElementById('mem-modal-content');
    if (!overlay || !content) return;

    var tags = (mem.tags || []);
    var tagsHtml = tags.map(function(t){ return tagChipHtml(t); }).join(' ');
    var emoColor = window.EMOTION_COLORS[mem.emotion] || '#94a3b8';

    var h = '';
    h += '<div class="mem-modal-header">';
    h += '<div>';
    h += '<div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:4px">Memory Key</div>';
    h += '<div style="display:flex;align-items:center;gap:6px">';
    h += '<span style="font-family:monospace;font-size:0.85rem;color:var(--accent-purple)">' + esc(mem.memory_key) + '</span>';
    h += '<button class="copy-btn" onclick="navigator.clipboard.writeText(\'' + esc(mem.memory_key).replace(/'/g,'\\\'') + '\');window.Nous.Core.toast(\'Key copied!\',\'info\')" title="Copy key">\uD83D\uDCCB</button>';
    h += '</div></div>';
    h += '<button class="mem-modal-close" onclick="closeMemModal()"><i data-lucide="x"></i></button>';
    h += '</div>';

    /* Full content */
    h += '<div class="mem-modal-content">' + esc(mem.content) + '</div>';

    /* Tags */
    if (tagsHtml) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span>' + tagsHtml + '</span></div>';
    }

    /* Emotion */
    if (mem.emotion) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Emotion</span><span>';
        h += '<span class="badge" style="background:' + emoColor + '22;color:' + emoColor + ';border:1px solid ' + emoColor + '44">' + esc(mem.emotion) + '</span>';
        if (mem.emotion_intensity != null) {
            h += ' <div class="modal-progress" style="display:inline-flex;width:120px;vertical-align:middle">';
            h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + (mem.emotion_intensity * 100) + '%;background:' + emoColor + '"></div></div>';
            h += '<span style="font-size:0.75rem;color:' + emoColor + '">' + mem.emotion_intensity.toFixed(2) + '</span></div>';
        }
        h += '</span></div>';
    }

    /* Importance */
    if (mem.importance != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Importance</span><span>';
        h += '<div class="modal-progress" style="display:inline-flex;width:160px">';
        h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + (mem.importance * 100) + '%;background:linear-gradient(90deg,var(--accent-purple),var(--accent-yellow))"></div></div>';
        h += '<span style="font-size:0.78rem;color:var(--accent-yellow);font-weight:600">' + mem.importance.toFixed(2) + '</span></div>';
        h += '</span></div>';
    }

    /* Strength */
    if (mem.strength != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Strength</span><span>';
        h += '<div class="modal-progress" style="display:inline-flex;width:160px">';
        h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + Math.min(mem.strength * 100, 100) + '%;background:linear-gradient(90deg,var(--accent-green),var(--accent-blue))"></div></div>';
        h += '<span style="font-size:0.78rem;color:var(--accent-green);font-weight:600">' + mem.strength.toFixed(3) + '</span></div>';
        h += '</span></div>';
    }

    /* Score (search) */
    if (mem._score != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Search Score</span><span class="badge badge-green">' + mem._score.toFixed(3) + '</span></div>';
    }

    /* Privacy */
    if (mem.privacy_level) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Privacy</span><span>' + esc(mem.privacy_level) + '</span></div>';
    }

    /* Source context */
    if (mem.source_context) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Source</span><span style="color:var(--text-muted)">' + esc(mem.source_context) + '</span></div>';
    }

    /* Body State */
    if (mem.body_state) {
        var bodyKeys = ['fatigue','warmth','arousal','heart_rate','pain'];
        /* Constants now from core/constants.js via adapter globals */
        var hasBody = bodyKeys.some(function(k){ return mem.body_state[k] != null; });
        if (hasBody) {
            h += '<div class=\"mem-modal-row\"><span class=\"mem-modal-key\">Body</span><span style=\"display:flex;flex-direction:column;gap:6px;flex:1\">';
            bodyKeys.forEach(function(k) {
                if (mem.body_state[k] != null) {
                    var val = mem.body_state[k];
                    var pct = Math.round(val * 100);
                    h += '<div style=\"display:flex;align-items:center;gap:8px\">';
                    h += '<span style=\"font-size:0.75rem;color:var(--text-muted);min-width:80px\">' + window.BODY_LABELS[k] + '</span>';
                    h += '<div style=\"flex:1;height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden\">';
                    h += '<div style=\"height:100%;width:' + pct + '%;background:' + window.BODY_BAR_COLORS[k] + ';border-radius:3px\"></div>';
                    h += '</div>';
                    h += '<span style=\"font-size:0.75rem;color:var(--text-muted);min-width:32px;text-align:right\">' + pct + '%</span>';
                    h += '</div>';
                }
            });
            h += '</span></div>';
        }
    }

    /* Emotion bar */
    if (mem.emotion) {
        h += '<div style=\"margin-bottom:16px\">' + renderEmotionBars(mem.emotion, mem.emotion_intensity) + '</div>';
    }

    /* Created at */
    if (mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>\uD83D\uDCC5 ' + relativeTime(mem.created_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.created_at).toLocaleString() + ')</span></span></div>';
    }

    /* State snapped at (if different from created) */
    if (mem.state_snapped_at && mem.state_snapped_at !== mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">State</span><span><i data-lucide="camera-off"></i> ' + relativeTime(mem.state_snapped_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.state_snapped_at).toLocaleString() + ')</span></span></div>';
    }

    /* Updated at */
    if (mem.updated_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>\uD83D\uDCC5 ' + relativeTime(mem.updated_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.updated_at).toLocaleString() + ')</span></span></div>';
    }

    /* Action buttons */
    h += '<div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">';
    h += '<button class="glass-btn glass-btn-danger" onclick="deleteMemory(\'' + esc(mem.memory_key).replace(/'/g,'\\\'') + '\')">\uD83D\uDDD1 Delete</button>';
    h += '<button class="glass-btn glass-btn-success" id="mem-modal-edit-btn">\u270F\uFE0F Edit</button>';
    h += '</div>';

    content.innerHTML = h;
    overlay.classList.add('show');
    /* Guard: remove first to prevent duplicate listeners on rapid reopen */
    document.removeEventListener('keydown', _memModalKeyHandler);
    document.addEventListener('keydown', _memModalKeyHandler);

    /* Bind the edit button - we store the mem object in closure */
    var editBtn = document.getElementById('mem-modal-edit-btn');
    if (editBtn) editBtn.onclick = function() { openEditModal(mem); };
}
window.openMemModal = openMemModal;

/* ================================================================
   closeMemModal — companion to openMemModal (rich version)
   ================================================================ */
function closeMemModal() {
    var overlay = document.getElementById('mem-modal-overlay');
    if (!overlay || !overlay.classList.contains('show')) return;
    overlay.classList.remove('show');
    document.removeEventListener('keydown', _memModalKeyHandler);
}
window.closeMemModal = closeMemModal;

function _memModalKeyHandler(e) {
    if (e.key === 'Escape') closeMemModal();
}

/* ================================================================
   openEditModal / openCreateModal
   ================================================================ */
var _editTags = [];

function _renderEditTags() {
    var wrap = document.getElementById('edit-tags-wrap');
    if (!wrap) return;
    /* Remove existing chips, keep the input */
    var chips = wrap.querySelectorAll('.tag-chip-edit');
    chips.forEach(function(c){ c.remove(); });
    var inp = document.getElementById('edit-tag-input');
    _editTags.forEach(function(tag, idx) {
        var hue = hashToHue(tag);
        var chip = document.createElement('span');
        chip.className = 'tag-chip-edit';
        chip.style.cssText = '--chip-hue:' + hue;
        chip.innerHTML = esc(tag) + ' <span class="tag-chip-remove" data-tidx="' + idx + '"><i data-lucide="x"></i></span>';
        wrap.insertBefore(chip, inp);
    });
    /* Bind remove buttons */
    wrap.querySelectorAll('.tag-chip-remove').forEach(function(btn) {
        btn.onclick = function(e) {
            e.stopPropagation();
            var i = parseInt(btn.dataset.tidx);
            _editTags.splice(i, 1);
            _renderEditTags();
        };
    });
}

function _addEditTag(val) {
    val = val.trim().toLowerCase();
    if (!val || _editTags.indexOf(val) !== -1) return;
    _editTags.push(val);
    _renderEditTags();
}

function openEditModal(mem) {
    document.getElementById('edit-modal-title').textContent = 'Edit Memory';
    document.getElementById('edit-content').value = mem.content || '';
    document.getElementById('edit-memory-key').value = mem.memory_key || '';

    var imp = mem.importance != null ? mem.importance : 0.5;
    document.getElementById('edit-importance').value = imp;
    document.getElementById('edit-imp-val').textContent = imp.toFixed(2);

    document.getElementById('edit-emotion').value = mem.emotion || '';

    var emoInt = mem.emotion_intensity != null ? mem.emotion_intensity : 0;
    document.getElementById('edit-emo-intensity').value = emoInt;
    document.getElementById('edit-emo-val').textContent = emoInt.toFixed(2);

    _editTags = (mem.tags || []).slice();
    _renderEditTags();

    document.getElementById('mem-edit-overlay').classList.add('active');
}

function openCreateModal() {
    document.getElementById('edit-modal-title').textContent = 'New Memory';
    document.getElementById('edit-content').value = '';
    document.getElementById('edit-memory-key').value = '';

    document.getElementById('edit-importance').value = 0.5;
    document.getElementById('edit-imp-val').textContent = '0.50';

    document.getElementById('edit-emotion').value = '';

    document.getElementById('edit-emo-intensity').value = 0;
    document.getElementById('edit-emo-val').textContent = '0.00';

    _editTags = [];
    _renderEditTags();

    document.getElementById('mem-edit-overlay').classList.add('active');
}

function closeEditModal() {
    document.getElementById('mem-edit-overlay').classList.remove('active');
}

/* ================================================================
   saveMemory
   ================================================================ */
async function saveMemory() {
    var contentVal = document.getElementById('edit-content').value.trim();
    if (!contentVal) { toast('Content is required', 'error'); return; }

    var key = document.getElementById('edit-memory-key').value;
    var imp = parseFloat(document.getElementById('edit-importance').value);
    var emoType = document.getElementById('edit-emotion').value;
    var emoInt = parseFloat(document.getElementById('edit-emo-intensity').value);

    var body = { content: contentVal, importance: imp, tags: _editTags.slice() };
    if (emoType) { body.emotion = emoType; body.emotion_intensity = emoInt; }

    try {
        if (key) {
            /* Update existing */
            await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key), {
                method: 'PUT', body: JSON.stringify(body)
            });
            toast('Memory updated', 'success');
        } else {
            /* Create new */
            await api('/api/memories/' + encodeURIComponent(S.persona), {
                method: 'POST', body: JSON.stringify(body)
            });
            toast('Memory created', 'success');
        }
        closeEditModal();
        closeMemModal();
        loadMemories();
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
}

/* ================================================================
   deleteMemory
   ================================================================ */
async function deleteMemory(key) {
    showConfirm('この記憶を削除しますか？この操作は取り消せません。', async function() {
        try {
            await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key), {
                method: 'DELETE'
            });
            toast('Memory deleted', 'success');
            closeMemModal();
            loadMemories();
        } catch (e) {
            toast('Delete failed: ' + e.message, 'error');
        }
    });
}
window.deleteMemory = deleteMemory;

/* ================================================================
   batchDeleteMemories
   ================================================================ */
async function batchDeleteMemories() {
    var keys = Array.from(S.mem.selected);
    if (keys.length === 0) { toast('No memories selected', 'error'); return; }
    showConfirm(keys.length + '件の記憶を削除しますか？この操作は取り消せません。', async function() {
        var ok = 0, failures = [];
        for (var i = 0; i < keys.length; i++) {
            try {
                await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(keys[i]), {
                    method: 'DELETE'
                });
                ok++;
            } catch (e) {
                failures.push({ key: keys[i], reason: e.message });
                console.error('[batchDelete] failed:', keys[i], e);
            }
        }
        S.mem.selected.clear();
        if (failures.length > 0) {
            var detail = failures.slice(0, 3).map(function(f){ return f.key + ' (' + f.reason + ')'; }).join(', ');
            var summary = ok + ' deleted, ' + failures.length + ' failed';
            if (failures.length > 3) summary += ' (see console for full list)';
            toast(summary + ': ' + detail, 'error');
            console.error('[batchDelete] failure detail:', failures);
        } else {
            toast('Deleted ' + ok + ' memories', 'success');
        }
        loadMemories();
    });
}

/* ================================================================
   toggleSelectMode
   ================================================================ */
function toggleSelectMode() {
    S.mem.selectMode = !S.mem.selectMode;
    if (!S.mem.selectMode) S.mem.selected.clear();
    loadMemories();
}

/* ================================================================
   toggleAdvancedSearch
   ================================================================ */
function toggleAdvancedSearch() {
    S.mem.advOpen = !S.mem.advOpen;
    var panel = document.getElementById('adv-search-panel');
    if (panel) {
        if (S.mem.advOpen) panel.classList.add('open');
        else panel.classList.remove('open');
    }
}

/* ================================================================
   applyAdvancedSearch
   ================================================================ */
function applyAdvancedSearch() {
    var df = document.getElementById('adv-date-from');
    var dt = document.getElementById('adv-date-to');
    var impMin = document.getElementById('adv-imp-min');
    var impMax = document.getElementById('adv-imp-max');
    var emo = document.getElementById('adv-emotion');

    S.mem.dateFrom = df ? df.value : '';
    S.mem.dateTo = dt ? dt.value : '';
    S.mem.impMin = impMin ? parseFloat(impMin.value) : 0;
    S.mem.impMax = impMax ? parseFloat(impMax.value) : 1;
    S.mem.emotion = emo ? emo.value : '';

    /* Gather active tag pills */
    S.mem.searchTags = [];
    document.querySelectorAll('.adv-filter-tag.active').forEach(function(pill) {
        S.mem.searchTags.push(pill.dataset.tag);
    });

    loadMemories(1);
}

/* ================================================================
   clearAdvancedSearch
   ================================================================ */
function clearAdvancedSearch() {
    S.mem.dateFrom = '';
    S.mem.dateTo = '';
    S.mem.impMin = 0;
    S.mem.impMax = 1;
    S.mem.searchTags = [];
    S.mem.emotion = '';
    S.mem.searchMode = 'hybrid';
    loadMemories(1);
}
})();
