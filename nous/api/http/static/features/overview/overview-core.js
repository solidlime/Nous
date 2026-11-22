/* =================================================================
   OVERVIEW CORE — Main loader, modals, charts, namespace registration
   Namespace: N.Features.Overview.*
   Depends on: N.Core.* (esc, api, truncate, relativeTime, fmtDate)
               overview-inventory.js (Inventory CRUD)
               window.* (safeSetHTML, Chart, lucide, destroyChart, chartOpts)
   ================================================================= */
N.Features.Overview = N.Features.Overview || {};

;(function() {
var S = window.S;
var { esc, api, truncate, relativeTime, fmtDate, safeSetHTML } = window.Nous.Core;
var BAR_COLORS = window.Nous.Core;
var EMOTION_BAR_COLORS = BAR_COLORS.EMOTION_BAR_COLORS || {};
var BODY_BAR_COLORS = BAR_COLORS.BODY_BAR_COLORS || {};

async function loadOverview() {
    const el = document.getElementById('overview-content');
    N.Components.skeleton.show('overview');
    // KPI 用の wiki 一覧 — 並行取得。失敗しても Overview 全体は落とさない
    const wikiPromise = api('/api/wiki/' + encodeURIComponent(S.persona), { suppressErrorToast: true })
        .then(w => (w && Array.isArray(w.pages) ? w.pages : null))
        .catch(() => null);
    try {
        const data = await api('/api/dashboard/' + encodeURIComponent(S.persona));
        if (!data || Object.keys(data).length === 0) {
            safeSetHTML(el, N.Components.skeleton.emptyState('pie-chart', 'Overview', 'No stats available for this persona yet.'));
            N.Core.refreshIcons();
            return;
        }
        // ── Self-portrait in hero section ──
        const portraitUrl = N.Core.auth.sign(data.latest_self_portrait);  // #102: <img src> はヘッダ不可
        const portraitEl = document.getElementById('overview-portrait');
        if (portraitUrl && portraitEl) {
            portraitEl.style.display = 'block';
            safeSetHTML(portraitEl, '<div class="ov-hero-portrait">'
                + '<img src="' + esc(portraitUrl) + '" alt="Self Portrait" data-ov-action="viewer" data-url="' + esc(portraitUrl) + '" data-kind="image">'
                + '</div>');
        } else if (portraitEl) {
            portraitEl.style.display = 'none';
        }

        // ── Generated Images History Grid (built here, rendered in template below) ──
        let genImagesHtml = '';
        const genImages = data.generated_images || [];
        if (genImages.length > 0) {
            genImagesHtml = '<div class="glass glass-hoverable p-6 mb-6">';
            genImagesHtml += '<div class="card-title"><i data-lucide="images"></i> Generated Images</div>';
            genImagesHtml += '<div class="image-history-grid">';
            genImages.forEach(img => {
                const prompt = img.revised_prompt || '';
                const tooltipAttr = prompt ? ' title="' + esc(prompt) + '"' : '';
                const badgeHtml = (img.self_portrait || img.is_self_portrait) ? '<span class="image-history-badge">🖼️ SP</span>' : '';
                genImagesHtml += '<div class="image-history-thumb" data-ov-action="viewer" data-url="' + esc(img.url) + '" data-kind="image" data-revised="' + esc(prompt) + '" data-negative="' + esc(img.negative_prompt || '') + '"' + tooltipAttr + '>';
                genImagesHtml += '<img src="' + esc(N.Core.auth.sign(img.url)) + '" alt="' + esc(img.filename) + '" loading="lazy">';  // #102
                genImagesHtml += badgeHtml;
                genImagesHtml += '</div>';
            });
            genImagesHtml += '</div>';
            genImagesHtml += '</div>';
        }
        // v4/B6: dashCache はセクション別。このローダが埋めるキーだけを書く。
        if (!S.dashCache) S.dashCache = { overview: null, items: null, images: null };
        S.dashCache.overview = { persona: data.persona, stats: data.stats, context: data.context,
            state_memories: data.state_memories };
        S.dashCache.items = data.items || [];
        S.dashCache.images = { latest_self_portrait: data.latest_self_portrait,
            generated_images: data.generated_images };
        const wikiPages = await wikiPromise;
        const stats = data.stats || {};
        const ctx = data.context || {};
        const equip = data.equipment || {};
        const items = data.items || [];

        // --- State memories: prefer state_memories, fallback to context_state ---
        const sm = data.state_memories || {};
        const physicalContent = (sm.physical_state?.content) || ctx.physical_state;
        const mentalContent = (sm.mental_state?.content) || ctx.mental_state;
        // --- Equipment display ---
        const EQUIP_SLOTS = ['top','bottom','shoes','outer','head','accessory_1','accessory_2','accessory_3'];
        let equipHtml = '<div class="ov-equip-list">';
        EQUIP_SLOTS.forEach(slot => {
            const current = equip[slot];
            const itemName = typeof current === 'string' ? current : (current ? (current.name || '') : '');
            equipHtml += '<div class="ov-equip-row">';
            equipHtml += '<span class="badge badge-blue ov-equip-slot">' + esc(slot) + '</span>';
            if (itemName) {
                equipHtml += '<span class="ov-equip-name">' + esc(itemName) + '</span>';
                equipHtml += '<button type="button" class="glass-btn" data-ov-action="unequip" data-slot="' + esc(slot) + '" title="Unequip"><i data-lucide="x"></i></button>';
            } else {
                equipHtml += '<span class="ov-equip-empty">empty</span>';
                const slotItems = items.filter(it => it.name);
                if (slotItems.length > 0) {
                    equipHtml += '<select class="glass-input ov-equip-select" data-ov-slot="' + esc(slot) + '"><option value="">equip...</option>';
                    slotItems.forEach(it => { equipHtml += '<option value="' + esc(it.name) + '">' + esc(it.name) + '</option>'; });
                    equipHtml += '</select>';
                }
            }
            equipHtml += '</div>';
        });
        equipHtml += '</div>';

        // --- Profile: user_info / persona_info / relationship ---
        const userInfo = ctx.user_info || {};
        const personaInfo = ctx.persona_info || {};
        const relStatus = ctx.relationship_status || ctx.relationship_type || '--';

        // --- Inventory items HTML ---
        let invHtml = '';
        if (items.length === 0) {
            invHtml = '<span class="ov-muted">No items in inventory</span>';
        } else {
            invHtml = '<div class="ov-inv-list">';
            items.forEach(it => {
                const desc = it.description || '';
                const truncDesc = desc.length > 40 ? desc.slice(0, 40) + '...' : desc;
                invHtml += '<div class="ov-inv-row">';
                invHtml += '<span class="badge badge-blue">' + esc(it.category || 'item') + '</span>';
                invHtml += '<span class="ov-inv-name" title="' + esc(desc) + '">' + esc(it.name) + '</span>';
                if (it.quantity > 1) invHtml += '<span class="ov-inv-qty">x' + it.quantity + '</span>';
                if (truncDesc) invHtml += '<span class="badge badge-purple" title="' + esc(desc) + '">' + esc(truncDesc) + '</span>';
                invHtml += '<button type="button" class="glass-btn" data-ov-action="edit-item" data-item="' + esc(it.name) + '" title="Edit item"><i data-lucide="pencil"></i></button>';
                invHtml += '<button type="button" class="glass-btn" data-ov-action="delete-item" data-item="' + esc(it.name) + '" title="Delete item"><i data-lucide="trash-2"></i></button>';
                invHtml += '</div>';
            });
            invHtml += '</div>';
        }

        // --- Mission Deck: md-* blocks (
        //     bars use data-fill/data-color — safeSetHTML strips style=) ---
        const personaInitial = String(S.persona || '?').charAt(0).toUpperCase();
        const relText = String(personaInfo.nickname || '') || ctx.relationship_status || ctx.relationship_type || '';
        const emoPct = Math.round((ctx.emotion_intensity || 0) * 100);
        const emoColor = EMOTION_BAR_COLORS[ctx.emotion] || EMOTION_BAR_COLORS.neutral || '';

        const barRow = (label, p, color, note) => '<div class="md-bar-row"><div class="md-bar-label"><span>'
            + esc(label) + (note ? ' (' + esc(note) + ')' : '') + '</span><b>' + p + '%</b></div>'
            + '<div class="md-bar"><div class="md-bar-fill" data-fill="' + p + '"'
            + (color ? ' data-color="' + esc(color) + '"' : '') + '></div></div></div>';

        const MINIS = [['fatigue', '疲労'], ['warmth', 'あたたかさ'], ['arousal', '覚醒'], ['heart_rate', '心拍']];
        const minisHtml = MINIS.map(([k, label]) => (
            stats[k] == null ? '' : barRow(label, Math.round(stats[k] * 100), BODY_BAR_COLORS[k] || '')
        )).join('');

        const placeHtml = stats.environment
            ? '<div class="md-ploc">現在地 — <b>' + esc(stats.environment) + '</b>'
                + (stats.place_since ? '　' + esc(relativeTime(stats.place_since)) + ' から' : '') + '</div>'
            : '';
        const lastConvHtml = ctx.last_conversation_time
            ? '<div class="md-ploc">最終会話 ' + esc(relativeTime(ctx.last_conversation_time)) + '</div>'
            : '';

        const kpi = (value, label) => '<div class="md-kpi"><div class="md-kpi-value">' + esc(value)
            + '</div><div class="md-kpi-label">' + esc(label) + '</div></div>';
        const num = v => (v == null || !Number.isFinite(Number(v))) ? '--' : Number(v).toLocaleString();
        const projectCount = wikiPages
            ? new Set(wikiPages.map(p => String(p.project || '').trim()).filter(Boolean)).size
            : null;
        const linkedPct = stats.linked_ratio == null ? '--' : (Math.round(stats.linked_ratio * 1000) / 10) + '%';

        const eventsHtml = (data.recent || []).slice(0, 5).map(m => '<div class="md-event"><b>'
            + esc(relativeTime(m.created_at)) + '</b><span class="md-tag">'
            + esc((m.tags && m.tags.length) ? m.tags[0] : 'memory') + '</span><span>'
            + esc(truncate(m.content || '', 90)) + '</span></div>').join('');

        const capacityRows = [];
        if (stats.linked_ratio != null) {
            capacityRows.push(barRow('想起カバレッジ', Math.round(stats.linked_ratio * 100), 'var(--accent-green)'));
        }
        if (projectCount != null && wikiPages.length > 0) {
            capacityRows.push(barRow('Wiki のプロジェクト紐付け',
                Math.round((projectCount / wikiPages.length) * 100), 'var(--accent-purple)'));
        }
        const capacityHtml = capacityRows.length > 0 ? capacityRows.join('') : '<div class="md-ploc">--</div>';

        const readingHtml = (wikiPages || []).slice(0, 5).map(p => '<div class="md-event"><b>'
            + esc(fmtDate(p.updated)) + '</b><span>'
            + esc(truncate(p.title || p.slug, 80)) + '</span></div>').join('');

        // --- Render ---
        safeSetHTML(el, `
        <div class="md-crumbs"><b>OVERVIEW</b> / 記憶の健康状態を一目で</div>

        <!-- Persona status band -->
        <div class="md-persona">
            <div class="md-persona-id">
                <div id="hero-portrait-slot"></div>
                <div class="md-avatar md-avatar-h">${esc(personaInitial)}</div>
                <div>
                    <h2>${esc(S.persona || '--')}</h2>
                    ${relText ? '<div class="md-rel">' + esc(relText) + '</div>' : ''}
                </div>
            </div>
            <div>
                ${barRow('気分 — ' + (ctx.emotion || 'neutral'), emoPct, emoColor)}
                ${placeHtml}
                ${lastConvHtml}
            </div>
            <div class="md-minis">${minisHtml}</div>
        </div>

        <!-- KPI row (delta は API に差分情報が無いため出さない) -->
        <div class="md-kpis">
            ${kpi(num(stats.total_count), 'Memories')}
            ${kpi(num(wikiPages ? wikiPages.length : null), 'Wiki pages')}
            ${kpi(num(projectCount), 'Projects')}
            ${kpi(linkedPct, 'Linked')}
        </div>

        <div class="md-grid2">
            <div class="md-pane">
                <h4>ACTIVITY <a href="#" data-ov-tab="timeline">Timeline →</a></h4>
                ${eventsHtml}
            </div>
            <div class="md-pane">
                <h4>CAPACITY</h4>
                ${capacityHtml}
            </div>
        </div>

        <div class="md-grid2">
            <div class="md-pane md-chat-pane">
                <h4>CHARA CHAT — ${esc(S.persona || '')} <a href="#" data-ov-tab="chat">Chat →</a></h4>
                <div class="md-ploc">直近の会話は Chat タブで。</div>
            </div>
            <div class="md-pane">
                <h4>TODAY'S READING <a href="#" data-ov-tab="wiki">Wiki →</a></h4>
                ${readingHtml || '<div class="md-ploc">--</div>'}
            </div>
        </div>

        <!-- Profile & Relationship -->
        <div class="glass p-4 mb-6">
            <div class="ov-section-title"><i data-lucide="user-circle"></i> Profile &amp; Relationship</div>
            ${Object.entries(userInfo).length ? Object.entries(userInfo).map(([k,v]) => '<div class="ov-quick-row ov-quick-tight"><span class="ov-quick-label">' + esc(k.replace(/_/g,' ')) + '</span><span class="ov-quick-value">' + esc(String(v)) + '</span></div>').join('') : '<span class="ov-muted">No user info</span>'}
            ${Object.entries(personaInfo).length ? Object.entries(personaInfo).map(([k,v]) => '<div class="ov-quick-row ov-quick-tight"><span class="ov-quick-label">' + esc(k.replace(/_/g,' ')) + '</span><span class="ov-quick-value ov-accent-purple">' + esc(String(v)) + '</span></div>').join('') : ''}
            <div class="ov-quick-row"><span class="ov-quick-label">Relationship</span><span class="ov-quick-value ov-accent-pink">${esc(relStatus)}</span></div>
            <div class="ov-quick-row"><span class="ov-quick-label">Physical</span><span class="ov-quick-value">${esc(physicalContent || '--')}</span></div>
            <div class="ov-quick-row"><span class="ov-quick-label">Mental</span><span class="ov-quick-value">${esc(mentalContent || '--')}</span></div>
        </div>

        <!-- Equipment -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="shield"></i> Equipment</div>
            ${equipHtml}
        </div>
        <!-- Relationship Highlights (from memory tags) -->
        ${data.relationship_highlights && data.relationship_highlights.length > 0 ? `
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="heart"></i> Relationship Highlights</div>
            <div class="ov-hl-list">
            ${data.relationship_highlights.map(h => `
                <div class="ov-hl-row">
                    <span class="ov-hl-icon"><i data-lucide="message-circle"></i></span>${esc(h.content || h)}
                </div>
            `).join('')}
            </div>
        </div>` : ''}
        <!-- Inventory -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title card-title-with-action"><span><i data-lucide="backpack"></i> Inventory</span><button type="button" class="glass-btn card-action-btn" data-ov-action="open-add-item">+ Add Item</button></div>
            ${invHtml}
        </div>
        ${genImagesHtml}
        <!-- Add Item Modal -->
        <div id="add-item-modal" class="ov-modal-overlay" role="dialog" aria-modal="true" aria-label="Add Inventory Item">
            <div class="ov-modal">
                <div class="ov-modal-title"><i data-lucide="plus"></i> Add Inventory Item</div>
                <div class="ov-modal-fields">
                    <input id="new-item-name" type="text" class="ov-field" placeholder="Item name *" aria-label="Item name (required)">
                    <input id="new-item-category" type="text" class="ov-field" placeholder="Category (e.g. clothing, weapon)" aria-label="Category">
                    <input id="new-item-desc" type="text" class="ov-field" placeholder="Description" aria-label="Description">
                    <input id="new-item-qty" type="number" value="1" min="1" class="ov-field" placeholder="Quantity" aria-label="Quantity">
                </div>
                <div class="ov-modal-actions">
                    <button type="button" class="glass-btn" data-ov-action="close-add-item">Cancel</button>
                    <button type="button" class="glass-btn" data-ov-action="save-new-item">Save</button>
                </div>
            </div>
        </div>
        <!-- Edit Item Modal -->
        <div id="edit-item-modal" class="ov-modal-overlay" role="dialog" aria-modal="true" aria-label="Edit Inventory Item">
            <div class="ov-modal">
                <div class="ov-modal-title"><i data-lucide="pencil"></i> Edit Inventory Item</div>
                <input type="hidden" id="edit-item-original-name" value="">
                <div class="ov-modal-fields">
                    <input id="edit-item-name" type="text" class="ov-field" placeholder="Item name *" aria-label="Item name (required)">
                    <input id="edit-item-category" type="text" class="ov-field" placeholder="Category (e.g. clothing, weapon)" aria-label="Category">
                    <textarea id="edit-item-desc" class="ov-field" placeholder="Description" rows="2" aria-label="Description"></textarea>
                    <input id="edit-item-qty" type="number" value="1" min="1" class="ov-field" placeholder="Quantity" aria-label="Quantity">
                    <input id="edit-item-tags" type="text" class="ov-field" placeholder="Tags (comma-separated)" aria-label="Tags (comma-separated)">
                </div>
                <div class="ov-modal-actions">
                    <button type="button" class="glass-btn" data-ov-action="close-edit-item">Cancel</button>
                    <button type="button" class="glass-btn" data-ov-action="save-edit-item">Save</button>
                </div>
            </div>
        </div>
        `);

        // safeSetHTML strips style= — apply data-fill/data-color to bar fills now
        if (N.Components.memoryCard && N.Components.memoryCard.applyDataStyles) {
            N.Components.memoryCard.applyDataStyles(el);
        }

        // --- Move portrait into hero slot (clone nodes, no innerHTML string copy) ---
        var heroSlot = document.getElementById('hero-portrait-slot');
        var portraitEl2 = document.getElementById('overview-portrait');
        if (heroSlot && portraitEl2 && portraitEl2.style.display !== 'none') {
            heroSlot.replaceChildren();
            Array.prototype.forEach.call(portraitEl2.childNodes, function (n) {
                heroSlot.appendChild(n.cloneNode(true));
            });
            portraitEl2.style.display = 'none';
        }

        N.Core.refreshIcons();
    } catch (e) {
        console.error('overview load failed:', e);
        safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load dashboard stats', function(){ loadOverview(); }));
        N.Core.refreshIcons();
    }
}
/* N.Features.Overview.loadOverview registered below */

// Register in namespace (CRUD helpers live in overview-inventory.js)
Object.assign(N.Features.Overview, {
    loadOverview: loadOverview,
});

/* CSP-safe delegation for overview actions (no inline onclick/onchange) */
if (typeof document !== "undefined" && !loadOverview._delegated) {
    loadOverview._delegated = true;
    document.addEventListener("click", function (e) {
        var tabLink = e.target && e.target.closest ? e.target.closest("[data-ov-tab]") : null;
        if (tabLink) {
            e.preventDefault();
            N.Core.switchTab(tabLink.getAttribute("data-ov-tab"));
            return;
        }
        var btn = e.target && e.target.closest ? e.target.closest("[data-ov-action]") : null;
        if (!btn) return;
        var action = btn.getAttribute("data-ov-action");
        var Ov = N.Features.Overview;
        if (action === "viewer" && N.Chat && N.Chat.attachments) {
            var data = null;
            if (btn.getAttribute("data-revised") || btn.getAttribute("data-negative")) {
                data = { revised_prompt: btn.getAttribute("data-revised") || "", negative_prompt: btn.getAttribute("data-negative") || "" };
            }
            N.Chat.attachments.openViewer(btn.getAttribute("data-url"), btn.getAttribute("data-kind") || "image", null, data);
        }
        else if (action === "unequip" && typeof Ov.unequipSlot === "function") Ov.unequipSlot(btn.dataset.slot);
        else if (action === "edit-item" && typeof Ov.openEditItemModal === "function") Ov.openEditItemModal(btn.dataset.item);
        else if (action === "delete-item" && typeof Ov.deleteItem === "function") Ov.deleteItem(btn.dataset.item);
        else if (action === "open-add-item" && typeof Ov.openAddItemModal === "function") Ov.openAddItemModal();
        else if (action === "close-add-item" && typeof Ov.closeAddItemModal === "function") Ov.closeAddItemModal();
        else if (action === "save-new-item" && typeof Ov.saveNewItem === "function") Ov.saveNewItem();
        else if (action === "close-edit-item" && typeof Ov.closeEditItemModal === "function") Ov.closeEditItemModal();
        else if (action === "save-edit-item" && typeof Ov.saveEditItem === "function") Ov.saveEditItem();
    });
    document.addEventListener("change", function (e) {
        var sel = e.target && e.target.closest ? e.target.closest("select[data-ov-slot]") : null;
        if (!sel) return;
        if (sel.value && typeof N.Features.Overview.changeEquipSlot === "function") {
            N.Features.Overview.changeEquipSlot(sel.getAttribute("data-ov-slot"), sel.value);
        }
    });
}
})();
