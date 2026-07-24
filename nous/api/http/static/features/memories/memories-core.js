/* =================================================================
   MEMORIES CORE — State initialization, data loading, event binding, helpers
   Namespace: N.Features.Memories.*
   Depends on: N.Core.* (esc, toast, api, truncate, relativeTime, showConfirm)
               N.Features.Memories.* (renderMemoryList, openMemModalByKey,
                 openCreateModal, toggleSelectMode, toggleAdvancedSearch,
                 applyAdvancedSearch, clearAdvancedSearch, batchDeleteMemories, _addEditTag)
                window.S, window.safeSetHTML, window.updateLastTime
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;
var { esc, toast, api, truncate, relativeTime, showConfirm } = window.Nous.Core;

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
    N.Components.skeleton.show('memories');

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
            safeSetHTML(el, N.Components.skeleton.emptyState('file-text', 'No memories', 'Try adjusting your search or create a new memory.'));
            updateLastTime();
            return;
        }
        N.Features.Memories.renderMemoryList(el, memories, tagOptions, totalPages, totalCount, isSearch, allKnownTags);
        bindMemoryEvents();
        updateLastTime();
    } catch (e) {
        console.error('memories load failed:', e);
        safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load memories', function(){ loadMemories(); }));
    }
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
})();
