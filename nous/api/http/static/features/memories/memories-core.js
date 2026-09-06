/* =================================================================
   MEMORIES CORE — State initialization, data loading, event binding, helpers
   Namespace: N.Features.Memories.*
   Depends on: N.Core.* (esc, toast, api, truncate, relativeTime, showConfirm)
               N.Features.Memories.* (renderMemoryList, openMemModalByKey,
                 openCreateModal, toggleSelectMode, toggleAdvancedSearch,
                 applyAdvancedSearch, clearAdvancedSearch, batchDeleteMemories, _addEditTag)
                window.S
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;
var { esc, toast, api, truncate, relativeTime, showConfirm, safeSetHTML, fmtDate } = window.Nous.Core;

/* ── State initialization ── */
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
    return '<span class="mem-tag-chip" data-hue="' + hue + '">' + esc(tag) + '</span>';
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
    N.Components.skeleton.show('memories');

    // --- Dashboard stats/stats/blocks/charts（Overview から移設）---
    if (!S.dashCache) {
        S.dashCache = await api('/api/dashboard/' + encodeURIComponent(S.persona));
    }
    const ds = S.dashCache;
    const stats = ds.stats || {};
    const str = ds.strengths || {};

    // Build stats HTML
    const tagDist = stats.tag_distribution || {};
    const emoDist = stats.emotion_distribution || {};
    const topTags = Object.entries(tagDist).sort((a,b)=>b[1]-a[1]).slice(0,5);
    const topEmo = Object.entries(emoDist).sort((a,b)=>b[1]-a[1]).slice(0,5);

    const MEMORY_TYPES = {
        'decision':  {color:'badge-blue',   icon:'<i data-lucide="compass"></i>'},
        'milestone': {color:'badge-green',  icon:'<i data-lucide="trophy"></i>'},
        'preference':{color:'badge-purple', icon:'<i data-lucide="heart"></i>'},
        'problem':   {color:'badge-red',    icon:'<i data-lucide="alert-triangle"></i>'},
        'emotional': {color:'badge-pink',   icon:'<i data-lucide="heart"></i>'},
    };
    const memTypeCounts = {};
    Object.entries(MEMORY_TYPES).forEach(([k])=>{ if(tagDist[k]) memTypeCounts[k]=tagDist[k]; });
    const hasMemTypes = Object.keys(memTypeCounts).length > 0;

    // Build blocks list HTML
    var blocksListHtml = '';
    if (ds.blocks && ds.blocks.length > 0) {
        ds.blocks.forEach(b => {
            const name = typeof b === 'string' ? b : (b.name || b.block_name || 'block');
            const content = typeof b === 'object' ? (b.content || b.value || '') : '';
            const priority = typeof b === 'object' ? b.priority : null;
            blocksListHtml += '<div class="memory-block-row">';
            blocksListHtml += '<div class="memory-block-head">';
            blocksListHtml += '<span class="memory-block-name">' + esc(name) + '</span>';
            if (priority != null) blocksListHtml += '<span class="badge badge-yellow">P' + esc(String(priority)) + '</span>';
            blocksListHtml += '<div class="memory-block-actions">';
            blocksListHtml += '<button type="button" class="glass-btn" data-block-action="edit" data-bname="' + esc(name) + '" data-bcontent="' + esc(content) + '" data-bpriority="' + (priority||0) + '"><i data-lucide="pencil"></i> Edit</button>';
            blocksListHtml += '<button type="button" class="glass-btn" data-block-action="delete" data-bname="' + esc(name) + '"><i data-lucide="trash-2"></i> Delete</button>';
            blocksListHtml += '</div></div>';
            if (content) blocksListHtml += '<div class="memory-muted-text">' + esc(truncate(String(content), 80)) + '</div>';
            blocksListHtml += '</div>';
        });
    } else {
        blocksListHtml = '<span class="memory-muted-text">No core memory blocks</span>';
    }

    // Build chart data
    const recent = ds.recent || [];
    const dayMap = {};
    const now = new Date();
    for (let i=6;i>=0;i--) { const d=new Date(now); d.setDate(d.getDate()-i); dayMap[d.toISOString().slice(0,10)]=0; }
    recent.forEach(m=>{ const d=(m.created_at||'').slice(0,10); if(d in dayMap) dayMap[d]++; });
    if (stats.daily_counts) { Object.entries(stats.daily_counts).forEach(([d,c])=>{ if(d in dayMap) dayMap[d]=c; }); }
    const dayLabels = Object.keys(dayMap).map(d=>fmtDate(d));
    const dayCounts = Object.values(dayMap);

    // Render dashboard sections atop memories list
    var dashboardHtml = '';

    // Memory Stats
    dashboardHtml += '<div class="glass glass-hoverable p-6 mb-6">';
    dashboardHtml += '<div class="card-title"><i data-lucide="bar-chart-3"></i> Memory Stats</div>';
    dashboardHtml += '<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">';
    dashboardHtml += '<div><div class="stat-value">' + (stats.total_count ?? '--') + '</div><div class="stat-label">Total Memories</div></div>';
    dashboardHtml += '<div><div class="stat-value stat-accent-green">' + (str.avg ?? '--') + '</div><div class="stat-label">Avg Strength</div></div>';
    dashboardHtml += '<div><div class="stat-value stat-accent-blue">' + (stats.tagged_ratio != null ? (stats.tagged_ratio*100).toFixed(1)+'%' : '--') + '</div><div class="stat-label">Tagged</div></div>';
    dashboardHtml += '<div><div class="stat-value stat-accent-yellow">' + (stats.linked_ratio != null ? (stats.linked_ratio*100).toFixed(1)+'%' : '--') + '</div><div class="stat-label">Linked</div></div>';
    dashboardHtml += '</div>';
    if (topTags.length) { dashboardHtml += '<div class="mb-4">' + topTags.map(([t,c])=>'<span class="badge badge-purple">'+esc(t)+' <span class="badge-count">('+c+')</span></span>').join(' ')+'</div>'; }
    if (hasMemTypes) { dashboardHtml += '<div class="mb-4">' + Object.entries(memTypeCounts).map(([t,c])=>'<span class="badge '+MEMORY_TYPES[t].color+'">'+MEMORY_TYPES[t].icon+' '+esc(t)+' <span class="badge-count">('+c+')</span></span>').join(' ')+'</div>'; }
    if (topEmo.length) { dashboardHtml += '<div>' + topEmo.map(([e,c])=>'<span class="badge badge-pink">'+esc(e)+' <span class="badge-count">('+c+')</span></span>').join(' ')+'</div>'; }
    dashboardHtml += '</div>';

    // Core Memory Blocks
    dashboardHtml += '<div class="glass glass-hoverable p-6 mb-6">';
    dashboardHtml += '<div class="card-title card-title-with-action"><span>🧠 Core Memory Blocks</span><button type="button" class="glass-btn card-action-btn" data-block-action="create"><i data-lucide="plus"></i> New Block</button></div>';
    dashboardHtml += blocksListHtml;
    dashboardHtml += '</div>';

    // Goals section
    var goalsListHtml = '';
    var effectiveGoals = ds.goals || [];
    if (effectiveGoals.length > 0) {
        effectiveGoals.forEach(function(item) {
            var content = typeof item === 'string' ? item : (item.content || item.description || item.title || JSON.stringify(item));
            var status = typeof item === 'object' ? (item.status || 'active').toLowerCase() : 'active';
            var icon;
            if (status === 'active') icon = '<i data-lucide="refresh-cw"></i>';
            else if (status === 'achieved' || status === 'fulfilled') icon = '<i data-lucide="check-circle"></i>';
            else if (status === 'cancelled') icon = '<i data-lucide="x-circle"></i>';
            else icon = '<i data-lucide="refresh-cw"></i>';
            goalsListHtml += '<div class="goal-row">';
            goalsListHtml += '<span>' + icon + '</span>';
            goalsListHtml += '<span class="goal-text">' + esc(content) + '</span>';
            var ts = typeof item === 'object' && (item.created_at || item.date);
            if (ts) goalsListHtml += '<span class="goal-time">' + relativeTime(ts) + '</span>';
            goalsListHtml += '</div>';
        });
    } else {
        goalsListHtml = '<span class="memory-muted-text">No goals</span>';
    }
    dashboardHtml += '<div class="glass glass-hoverable p-6 mb-6">';
    dashboardHtml += '<div class="card-title"><i data-lucide="target"></i> Goals <span class="card-title-count">(' + effectiveGoals.length + ')</span></div>';
    dashboardHtml += '<div class="goals-scroll">' + goalsListHtml + '</div>';
    dashboardHtml += '</div>';

    // Charts placeholders
    dashboardHtml += '<div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">';
    dashboardHtml += '<div class="glass p-6"><div class="card-title"><i data-lucide="calendar"></i> 7-Day Timeline</div><div class="chart-box"><canvas id="chart-timeline"></canvas></div></div>';
    dashboardHtml += '<div class="glass p-6"><div class="card-title"><i data-lucide="tag"></i> Tag Distribution</div><div class="chart-box"><canvas id="chart-tags"></canvas></div></div>';
    dashboardHtml += '</div>';

    // Inject dashboard HTML at the beginning of the memories content area
    safeSetHTML(el, dashboardHtml + '<div id="memories-list-section"></div>');
    // Redirect subsequent rendering to the list section
    el = document.getElementById('memories-list-section');

    // --- Chart rendering (async, after DOM is populated) ---
    setTimeout(function(){
        S.charts = S.charts || {};
        N.Components.chart.destroy('chart-timeline');
        N.Components.chart.destroy('chart-tags');
        var tlCtx = document.getElementById('chart-timeline');
        if (tlCtx) {
            S.charts['chart-timeline'] = new Chart(tlCtx, {
                type:'bar',
                data:{labels:dayLabels,datasets:[{label:'Memories',data:dayCounts,backgroundColor:'rgba(0,122,255,0.5)',borderColor:'#007aff',borderWidth:1,borderRadius:6}]},
                options:N.Components.chart.defaults({plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{stepSize:1}},x:{}}})
            });
        }
        var allTags = Object.entries(tagDist).sort((a,b)=>b[1]-a[1]).slice(0,8);
        var tgCtx = document.getElementById('chart-tags');
        if (tgCtx && allTags.length) {
            S.charts['chart-tags'] = new Chart(tgCtx, {
                type:'doughnut',
                data:{labels:allTags.map(t=>t[0]),datasets:[{data:allTags.map(t=>t[1]),backgroundColor:N.Core.CHART_COLORS.slice(0,allTags.length),borderWidth:0}]},
                options:{...N.Components.chart.defaults(),cutout:'60%'}
            });
        } else if (tgCtx) {
            safeSetHTML(tgCtx.parentElement, '<div>No tags yet</div>');
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }, 100);

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
        if (!memories || memories.length === 0) {
            safeSetHTML(el, N.Components.skeleton.emptyState('file-text', '記憶がありません', '検索条件を変えるか、新しい記憶を作成してください。'));
            N.Core.updateLastTime();
            return;
        }
        N.Features.Memories.renderMemoryList(el, memories, tagOptions, totalPages, totalCount, isSearch, allKnownTags);
        bindMemoryEvents();
        N.Core.updateLastTime();
    } catch (e) {
        console.error('memories load failed:', e);
        safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load memories', function(){ loadMemories(); }));
    }
}
/* N.Features.Memories.loadMemories registered below */

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
            if (e.target.type === 'checkbox') return;
            var key = card.getAttribute('data-memkey');
            if (!key) return;
            N.Features.Memories.openMemModalByKey(key);
        };
    });

    /* New Memory button */
    var newBtn = document.getElementById('mem-new-btn');
    if (newBtn) newBtn.onclick = function() { N.Features.Memories.openCreateModal(); };

    /* Select toggle */
    var selToggle = document.getElementById('mem-select-toggle');
    if (selToggle) selToggle.onclick = function() { N.Features.Memories.toggleSelectMode(); };

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
    if (advToggle) advToggle.onclick = function() { N.Features.Memories.toggleAdvancedSearch(); };

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
    if (batchDel) batchDel.onclick = function() { N.Features.Memories.batchDeleteMemories(); };

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
    if (advApply) advApply.onclick = function() { N.Features.Memories.applyAdvancedSearch(); };

    /* Advanced search: Clear */
    var advClear = document.getElementById('adv-clear-btn');
    if (advClear) advClear.onclick = function() { N.Features.Memories.clearAdvancedSearch(); };

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
            N.Features.Memories._addEditTag(val);
            tagInput.value = '';
        }
    };
}

Object.assign(N.Features.Memories, {
    hashToHue: hashToHue,
    tagChipHtml: tagChipHtml,
    _sortMemories: _sortMemories,
    _filterMemories: _filterMemories,
    loadMemories: loadMemories,
    bindMemoryEvents: bindMemoryEvents,
});

/* CSP-safe delegation for Core Memory Block buttons (no inline onclick) */
if (typeof document !== "undefined" && !bindMemoryEvents._blockDelegated) {
    bindMemoryEvents._blockDelegated = true;
    document.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest ? e.target.closest("[data-block-action]") : null;
        if (!btn) return;
        var action = btn.getAttribute("data-block-action");
        var Ov = window.Nous && window.Nous.Features && window.Nous.Features.Overview;
        if (!Ov) return;
        if (action === "create" && typeof Ov.showCreateBlock === "function") Ov.showCreateBlock();
        else if (action === "edit" && typeof Ov.showEditBlock === "function") {
            Ov.showEditBlock(btn.dataset.bname, btn.dataset.bcontent, parseInt(btn.dataset.bpriority || "0", 10));
        } else if (action === "delete" && typeof Ov.deleteBlock === "function") {
            Ov.deleteBlock(btn.dataset.bname);
        }
    });
}
})();
