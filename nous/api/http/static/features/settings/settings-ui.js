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
    general: '<i data-lucide="settings"></i>',
    workers: '<i data-lucide="clock"></i>',
    memory: '<i data-lucide="layers"></i>',
    search: '<i data-lucide="sliders-horizontal"></i>',
    mcp_client: '<i data-lucide="plug"></i>',
    wiki: '<i data-lucide="book-open"></i>',
    irodori: '<i data-lucide="music"></i>',
    memory_enrichment: '<i data-lucide="sparkles"></i>',
    cors: '<i data-lucide="shield-check"></i>',
    plugin: '<i data-lucide="puzzle"></i>',
    api_keys: '<i data-lucide="key"></i>'
};

const CATEGORY_DESCRIPTIONS = {
    server: 'Server bind address and port. Changes require a full server restart.',
    mcp_security: 'MCP DNS-rebinding protection: which Host/Origin headers may call /mcp. Changes require a full server restart.',
    embedding: 'Embedding model configuration for vector search. Reload takes 10-60s.',
    reranker: 'Cross-encoder reranker for search result quality. Reload takes 5-30s.',
    qdrant: 'Qdrant vector database connection settings.',
    general: 'General settings: timezone, logging, thresholds, search engine.',
    workers: 'Resident worker intervals: proactive turns, life activities, cue monitoring.',
    memory: 'Memory thresholds: write-duplicate detection, corroboration/interference, mot thoughts.',
    search: 'Search pipeline tuning: FTS fallback bar, rerank stage, recency decay.',
    mcp_client: 'MCP client request timeout (http and stdio).',
    wiki: 'Wiki and journal compilation: cycle, topics, sources, research.',
    irodori: 'Irodori TTS server connection and generation limits.',
    memory_enrichment: 'Auxiliary LLM (memory extraction / brain). Changes require a full server restart.',
    cors: 'CORS middleware (baked at startup). Changes require a full server restart.',
    plugin: 'Plugin system (baked at startup). Changes require a full server restart.',
    api_keys: 'LLM provider API keys (hot-reload overrides).'
};

/* ── Category display order (consistent across renders) ── */
const CATEGORY_ORDER = [
    // ── Safe hot-reload groups (tuning, no restart) ──
    'general', 'workers', 'memory', 'search', 'mcp_client',
    'wiki', 'irodori',
    // ── Restart-required operational groups ──
    'memory_enrichment', 'cors', 'plugin', 'api_keys',
    // ── Infra / dangerous groups (heavy reload or restart, keep last) ──
    'server', 'mcp_security', 'embedding', 'reranker',
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
