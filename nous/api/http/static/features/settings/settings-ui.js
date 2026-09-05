/* =================================================================
   SETTINGS UI — Constants, search/filter, category toggle
   Namespace: N.Features.Settings.*
   Depends on: N.Core.*
   ================================================================= */
N.Features.Settings = N.Features.Settings || {};

;(function() {
var { esc, safeSetHTML } = window.Nous.Core;

const CATEGORY_ICONS = {
    server: '<i data-lucide="monitor"></i>',
    mcp_security: '<i data-lucide="shield"></i>',
    embedding: '<i data-lucide="brain"></i>',
    reranker: '<i data-lucide="search"></i>',
    qdrant: '<i data-lucide="package"></i>',
    general: '<i data-lucide="settings"></i>'
};

const CATEGORY_DESCRIPTIONS = {
    server: 'Server bind address and port. Changes require a full server restart.',
    mcp_security: 'MCP DNS-rebinding protection: which Host/Origin headers may call /mcp. Changes require a full server restart.',
    embedding: 'Embedding model configuration for vector search. Reload takes 10-60s.',
    reranker: 'Cross-encoder reranker for search result quality. Reload takes 5-30s.',
    qdrant: 'Qdrant vector database connection settings.',
    general: 'General settings: timezone, logging, thresholds, search engine.'
};

/* ── Category display order (consistent across renders) ── */
const CATEGORY_ORDER = [
    'general', 'server', 'mcp_security', 'embedding', 'reranker',
    'qdrant'
];

/* ═══════════════════════════════════════════════════════════════════
   SOURCE ICON
   ═══════════════════════════════════════════════════════════════════ */

function sourceIcon(src) {
    if (src === 'env') return '<span class="setting-source source-env" title="Set via environment variable"><i data-lucide="globe"></i> env</span>';
    if (src === 'override') return '<span class="setting-source source-override" title="Set via WebUI override"><i data-lucide="edit-3"></i> override</span>';
    return '<span class="setting-source source-default" title="Using default value"><i data-lucide="clipboard-list"></i> default</span>';
}

/* ═══════════════════════════════════════════════════════════════════
   SEARCH / FILTER
   ═══════════════════════════════════════════════════════════════════ */

function filterSettings(query) {
    var q = query.toLowerCase().trim();
    var clearBtn = document.getElementById('settings-search-clear');
    if (clearBtn) clearBtn.style.display = q ? 'block' : 'none';

    document.querySelectorAll('.setting-category-card').forEach(function(card) {
        var catText = (card.dataset.searchtext || '').toLowerCase();
        var rows = card.querySelectorAll('.setting-row');

        if (!q) {
            card.style.display = '';
            rows.forEach(function(r) { r.style.display = ''; });
            return;
        }

        var catMatch = catText.includes(q);
        var anyRowMatch = false;

        rows.forEach(function(r) {
            var rowText = (r.dataset.searchtext || '').toLowerCase();
            if (catMatch || rowText.includes(q)) {
                r.style.display = '';
                anyRowMatch = true;
            } else {
                r.style.display = 'none';
            }
        });

        card.style.display = (catMatch || anyRowMatch) ? '' : 'none';

        /* Auto-expand matching categories */
        if (catMatch || anyRowMatch) {
            var cat = card.dataset.category;
            var body = document.getElementById('cat-body-' + cat);
            var toggle = document.getElementById('cat-toggle-' + cat);
            if (body) body.style.display = 'block';
            if (toggle) toggle.textContent = '▼';
        }
    });
}

/* ═══════════════════════════════════════════════════════════════════
   CATEGORY TOGGLE
   ═══════════════════════════════════════════════════════════════════ */

function toggleCategory(catId) {
    var body = document.getElementById('cat-body-' + catId);
    var toggle = document.getElementById('cat-toggle-' + catId);
    if (!body || !toggle) return;
    if (body.style.display === 'none') {
        body.style.display = 'block';
        toggle.textContent = '▼';
    } else {
        body.style.display = 'none';
        toggle.textContent = '▶';
    }
}

Object.assign(N.Features.Settings, {
    CATEGORY_ICONS: CATEGORY_ICONS,
    CATEGORY_DESCRIPTIONS: CATEGORY_DESCRIPTIONS,
    CATEGORY_ORDER: CATEGORY_ORDER,
    sourceIcon: sourceIcon,
    filterSettings: filterSettings,
    toggleCategory: toggleCategory,
});
})();
