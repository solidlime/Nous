/* =================================================================
   PROJECTS TAB — project:<slug> 単位の文脈ビュー（kanban #8）
   Namespace: N.Features.Projects.*
   集計はサーバ（GET /api/project/{persona}/{slug}/context）で済む。
   ここは slug 入力・描画・wiki への遷移だけ。
   ================================================================= */
N.Features.Projects = N.Features.Projects || {};

;(function() {
var S = window.S;
var { esc, api, safeSetHTML } = window.Nous.Core;

var STATE = { slug: "", loading: false };

function persona() { return (S && S.persona) || ""; }

function contextUrl(slug) {
    return '/api/project/' + encodeURIComponent(persona()) + '/' + encodeURIComponent(slug) + '/context';
}

function section(title, bodyHtml, count) {
    var badge = (typeof count === 'number') ? ' <span class="proj-count">(' + count + ')</span>' : '';
    return '<div class="glass p-4 mb-4">' +
        '<div class="proj-section-title">' + esc(title) + badge + '</div>' +
        bodyHtml +
        '</div>';
}

function empty(text) {
    return '<div class="proj-empty">' + esc(text) + '</div>';
}

function itemList(items, emptyText, opts) {
    if (!items || !items.length) return empty(emptyText);
    var withDate = !!(opts && opts.withDate);
    return items.map(function(it) {
        var when = withDate && it.created_at
            ? '<span class="proj-row-meta">' + esc(String(it.created_at).slice(0, 16).replace('T', ' ')) + '</span>'
            : '';
        return '<div class="proj-row">' +
            '<div class="proj-row-text">' + esc(it.content) + when + '</div>' +
            '</div>';
    }).join('');
}

function wikiList(pages) {
    if (!pages || !pages.length) return empty('このプロジェクトの wiki ページはまだ無い');
    return pages.map(function(p) {
        return '<div class="proj-row">' +
            '<a href="#" data-project-wiki="' + esc(p.slug) + '" class="proj-row-link">' +
            esc(p.title || p.slug) + '</a>' +
            '<span class="proj-row-meta">' + esc(String(p.updated || '').slice(0, 16)) + '</span>' +
            '</div>';
    }).join('');
}

function render(data) {
    var el = document.getElementById('project-content');
    if (!el) return;
    if (!data || !data.counts) { safeSetHTML(el, empty('データが空')); return; }
    var c = data.counts;
    var head = '<div class="glass p-4 mb-4 proj-badge-row">' +
        '<span>記憶 <strong>' + c.memories + '</strong></span>' +
        '<span>決定事項 <strong>' + c.decisions + '</strong></span>' +
        '<span>未解決の問い <strong>' + c.open_questions + '</strong></span>' +
        '<span>wiki <strong>' + c.wiki + '</strong></span>' +
        '<span class="proj-tag">' + esc(data.tag) + '</span>' +
        '</div>';
    safeSetHTML(el,
        head +
        section('決定事項', itemList(data.decisions, 'このプロジェクトの決定事項はまだ無い', { withDate: true }), c.decisions) +
        section('未解決の問い', itemList(data.open_questions, '未解決の問いは無い', { withDate: true }), c.open_questions) +
        section('Wiki', wikiList(data.wiki), c.wiki) +
        section('タイムライン', itemList(data.timeline, 'このプロジェクトの記憶はまだ無い', { withDate: true }), c.memories)
    );
}

async function loadProject(slug) {
    var target = (slug || STATE.slug || '').trim();
    var statusEl = document.getElementById('project-status');
    var el = document.getElementById('project-content');
    if (!target) {
        if (statusEl) statusEl.textContent = 'slug を入れて';
        return;
    }
    if (!persona()) {
        if (statusEl) statusEl.textContent = 'persona が未選択';
        return;
    }
    if (STATE.loading) return;
    STATE.slug = target;
    STATE.loading = true;
    if (statusEl) statusEl.textContent = 'loading…';
    try {
        var data = await api(contextUrl(target));
        render(data);
        if (statusEl) statusEl.textContent = 'loaded';
    } catch (e) {
        console.error('project context load failed:', e);
        if (statusEl) statusEl.textContent = 'load failed';
        if (el) safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load project context', function(){ loadProject(target); }));
    } finally {
        STATE.loading = false;
    }
}

function init() {
    var input = document.getElementById('project-slug-input');
    var btn = document.getElementById('project-load-btn');
    if (btn) {
        btn.addEventListener('click', function() { loadProject(input ? input.value : ''); });
    }
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); loadProject(input.value); }
        });
    }
    // wiki ページへの遷移ができたら嬉しいが、タブ間の move は別 API。今は slug を出すだけ。
    var el = document.getElementById('project-content');
    if (el) {
        el.addEventListener('click', function(e) {
            var link = e.target.closest('[data-project-wiki]');
            if (!link) return;
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('project:open-wiki', { detail: { slug: link.getAttribute('data-project-wiki') } }));
        });
    }
}

N.Core.whenReady(function() {
    init();
    var container = document.querySelector('main.main-content');
    if (container) {
        var obs = new MutationObserver(function(mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var m = mutations[i];
                if (m.type !== 'attributes' || m.attributeName !== 'class') continue;
                var el = m.target;
                if (el.classList && el.classList.contains('tab-panel') && el.classList.contains('active') && el.id === 'tab-projects') {
                    if (STATE.slug && !STATE.loading) loadProject(STATE.slug);
                }
            }
        });
        obs.observe(container, { attributes: true, attributeFilter: ['class'], subtree: true });
    }
});

Object.assign(N.Features.Projects, { loadProject: loadProject, render: render });
})();
