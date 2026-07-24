/* =================================================================
   MEMORIES SEARCH — Advanced search toggle, apply, clear
   Namespace: N.Features.Memories.*
   Depends on: N.Features.Memories.loadMemories
               window.S, window.safeSetHTML
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;

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

    N.Features.Memories.loadMemories(1);
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
    N.Features.Memories.loadMemories(1);
}

Object.assign(N.Features.Memories, {
    toggleAdvancedSearch: toggleAdvancedSearch,
    applyAdvancedSearch: applyAdvancedSearch,
    clearAdvancedSearch: clearAdvancedSearch,
});
})();
