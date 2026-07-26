/* =================================================================
   OVERVIEW CORE — Main loader, modals, charts, namespace registration
   Namespace: N.Features.Overview.*
   Depends on: N.Core.* (esc, toast, api, truncate, relativeTime, fmtDate)
               overview-blocks.js (Block CRUD)
               overview-inventory.js (Inventory CRUD)
               window.* (safeSetHTML, Chart, lucide, destroyChart, chartOpts)
   ================================================================= */
N.Features.Overview = N.Features.Overview || {};

;(function() {
var S = window.S;
var { esc, toast, api, truncate, relativeTime, fmtDate, safeSetHTML } = window.Nous.Core;

async function loadOverview() {
    const el = document.getElementById('overview-content');
    N.Components.skeleton.show('overview');
    try {
        const data = await api('/api/dashboard/' + encodeURIComponent(S.persona));
        if (!data || Object.keys(data).length === 0) {
            safeSetHTML(el, N.Components.skeleton.emptyState('pie-chart', 'Overview', 'No stats available for this persona yet.'));
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }
        // ── Self-portrait in hero section ──
        const portraitUrl = data.latest_self_portrait;
        const portraitEl = document.getElementById('overview-portrait');
        if (portraitUrl && portraitEl) {
            portraitEl.style.display = 'block';
            safeSetHTML(portraitEl, '<div class="ov-hero-portrait">'
                + '<img src="' + esc(portraitUrl) + '" alt="Self Portrait" onclick="N.Chat.attachments.openViewer(\'' + esc(portraitUrl) + '\',\'image\')" style="cursor:pointer">'
                + '</div>');
        } else if (portraitEl) {
            portraitEl.style.display = 'none';
        }

        // ── Generated Images History Grid ──
        const imagesGridEl = document.getElementById('overview-images-grid');
        if (imagesGridEl) {
            const genImages = data.generated_images || [];
            if (genImages.length > 0) {
                let gridHtml = '<div class="glass glass-hoverable p-6 mb-6">';
                gridHtml += '<div class="card-title"><i data-lucide="images"></i> Generated Images</div>';
                gridHtml += '<div class="image-history-grid">';
                genImages.forEach(img => {
                    const prompt = img.revised_prompt || '';
                    const tooltipAttr = prompt ? ' title="' + esc(prompt) + '"' : '';
                    const badgeHtml = img.is_self_portrait ? '<span class="image-history-badge">🖼️ SP</span>' : '';
                    gridHtml += '<div class="image-history-thumb"' + tooltipAttr + ' onclick="N.Chat.attachments.openViewer(\'' + esc(img.url) + '\',\'image\',null,{revised_prompt:\'' + esc(prompt).replace(/'/g, "\\'") + '\'})">';
                    gridHtml += '<img src="' + esc(img.url) + '" alt="' + esc(img.filename) + '" loading="lazy">';
                    gridHtml += badgeHtml;
                    gridHtml += '</div>';
                });
                gridHtml += '</div>';
                gridHtml += '</div>';
                imagesGridEl.style.display = 'block';
                safeSetHTML(imagesGridEl, gridHtml);
            } else {
                imagesGridEl.style.display = 'none';
            }
        }
        S.dashCache = data;
        const stats = data.stats || {};
        const ctx = data.context || {};
        const equip = data.equipment || {};
        const items = data.items || [];
        const str = data.strengths || {};

        // --- State memories: prefer state_memories, fallback to context_state ---
        const sm = data.state_memories || {};
        const physicalContent = (sm.physical_state?.content) || ctx.physical_state;
        const mentalContent = (sm.mental_state?.content) || ctx.mental_state;
        // --- Build tag/emotion distributions from stats ---
        const tagDist = stats.tag_distribution || {};
        const emoDist = stats.emotion_distribution || {};
        const topTags = Object.entries(tagDist).sort((a,b) => b[1]-a[1]).slice(0,5);
        const topEmo = Object.entries(emoDist).sort((a,b) => b[1]-a[1]).slice(0,5);

        // --- Memory Type Distribution (decision/milestone/preference/problem/emotional) ---
        const MEMORY_TYPES = {
            'decision':  {color: 'badge-blue',   icon: '<i data-lucide="compass"></i>'},
            'milestone': {color: 'badge-green',  icon: '<i data-lucide="trophy"></i>'},
            'preference':{color: 'badge-purple', icon: '<i data-lucide="heart"></i>'},
            'problem':   {color: 'badge-red',    icon: '<i data-lucide="alert-triangle"></i>'},
            'emotional': {color: 'badge-pink',   icon: '<i data-lucide="heart"></i>'},
        };
        const memTypeCounts = {};
        Object.entries(MEMORY_TYPES).forEach(([k]) => {
            if (tagDist[k]) memTypeCounts[k] = tagDist[k];
        });
        const hasMemTypes = Object.keys(memTypeCounts).length > 0;

        // --- Equipment display ---
        const EQUIP_SLOTS = ['top','bottom','shoes','outer','head','accessory_1','accessory_2','accessory_3'];
        let equipHtml = '<div style="display:grid;gap:6px;margin-top:8px">';
        EQUIP_SLOTS.forEach(slot => {
            const current = equip[slot];
            const itemName = typeof current === 'string' ? current : (current ? (current.name || '') : '');
            equipHtml += '<div style="display:flex;align-items:center;gap:8px">';
            equipHtml += '<span class="badge badge-blue" style="min-width:80px;text-align:center">' + esc(slot) + '</span>';
            if (itemName) {
                equipHtml += '<span style="flex:1;font-size:0.85rem;color:var(--text-secondary)">' + esc(itemName) + '</span>';
                equipHtml += '<button data-slot="' + esc(slot) + '" onclick="N.Features.Overview.unequipSlot(this.dataset.slot)" style="font-size:0.72rem;padding:2px 8px;border-radius:4px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer" title="Unequip"><i data-lucide="x"></i></button>';
            } else {
                equipHtml += '<span style="flex:1;font-size:0.82rem;color:var(--text-muted);font-style:italic">empty</span>';
                const slotItems = items.filter(it => it.name);
                if (slotItems.length > 0) {
                    equipHtml += '<select data-slot="' + esc(slot) + '" onchange="if(this.value) N.Features.Overview.changeEquipSlot(this.dataset.slot, this.value)" style="font-size:0.78rem;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:4px;color:var(--text-secondary);padding:2px 4px"><option value="">equip...</option>';
                    slotItems.forEach(it => { equipHtml += '<option value="' + esc(it.name) + '">' + esc(it.name) + '</option>'; });
                    equipHtml += '</select>';
                }
            }
            equipHtml += '</div>';
        });
        equipHtml += '</div>';

        // --- Core blocks ---
        let blocksHtml = '';
        if (data.blocks && data.blocks.length > 0) {
            data.blocks.forEach(b => {
                const name = typeof b === 'string' ? b : (b.name || b.block_name || 'block');
                const content = typeof b === 'object' ? (b.content || b.value || '') : '';
                const priority = typeof b === 'object' ? b.priority : null;
                blocksHtml += '<div style="padding:10px 0;border-bottom:1px solid var(--glass-border)">';
                blocksHtml += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
                blocksHtml += '<span style="font-weight:600;color:var(--accent-purple);font-size:0.85rem">' + esc(name) + '</span>';
                if (priority != null) blocksHtml += '<span class="badge badge-yellow">P' + esc(String(priority)) + '</span>';
                blocksHtml += '<div style="display:flex;gap:6px;margin-left:auto">';
                blocksHtml += '<button class="glass-btn" data-bname="' + esc(name) + '" data-bcontent="' + esc(content) + '" data-bpriority="' + (priority || 0) + '" onclick="var el=this;N.Features.Overview.showEditBlock(el.dataset.bname,el.dataset.bcontent,parseInt(el.dataset.bpriority||0))" style="padding:3px 10px;font-size:0.75rem"><i data-lucide="pencil"></i> Edit</button>';
                blocksHtml += '<button class="glass-btn" data-bname="' + esc(name) + '" onclick="N.Features.Overview.deleteBlock(this.dataset.bname)" style="padding:3px 10px;font-size:0.75rem;color:var(--accent-red)"><i data-lucide="trash-2"></i> Delete</button>';
                blocksHtml += '</div>';
                blocksHtml += '</div>';
                if (content) blocksHtml += '<div style="font-size:0.82rem;color:var(--text-muted)">' + esc(truncate(String(content), 80)) + '</div>';
                blocksHtml += '</div>';
            });
        } else {
            blocksHtml = '<span style="color:var(--text-muted)">No core memory blocks</span>';
        }

        // --- Goals ---
        function getStatusIcon(status) {
            if (status === 'active') return '<i data-lucide="refresh-cw"></i>';
            if (status === 'achieved' || status === 'fulfilled') return '<i data-lucide="check-circle"></i>';
            if (status === 'cancelled') return '<i data-lucide="x-circle"></i>';
            return '<i data-lucide="refresh-cw"></i>';
        }

        function renderGoalItems(goalItems, label) {
            if (!goalItems || goalItems.length === 0) return '<span style="color:var(--text-muted)">No ' + label + '</span>';
            let html = '';
            goalItems.forEach(item => {
                const content = typeof item === 'string' ? item : (item.content || item.description || item.title || JSON.stringify(item));
                const status = typeof item === 'object' ? (item.status || 'active').toLowerCase() : 'active';
                const icon = getStatusIcon(status);
                html += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0">';
                html += '<span>' + icon + '</span>';
                html += '<span style="flex:1;font-size:0.85rem;color:var(--text-secondary)">' + esc(content) + '</span>';
                const ts = typeof item === 'object' && (item.created_at || item.date);
                if (ts) html += '<span style="font-size:0.72rem;color:var(--text-muted)">' + relativeTime(ts) + '</span>';
                html += '</div>';
            });
            return html;
        }

        const effectiveGoals = data.goals || [];

        // --- Profile: user_info / persona_info / relationship ---
        const userInfo = ctx.user_info || {};
        const personaInfo = ctx.persona_info || {};
        const relStatus = ctx.relationship_status || ctx.relationship_type || '--';

        // --- Inventory items HTML ---
        let invHtml = '';
        if (items.length === 0) {
            invHtml = '<span style="color:var(--text-muted)">No items in inventory</span>';
        } else {
            invHtml = '<div style="display:grid;gap:4px">';
            items.forEach(it => {
                const desc = it.description || '';
                const truncDesc = desc.length > 40 ? desc.slice(0, 40) + '...' : desc;
                invHtml += '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04)">';
                invHtml += '<span class="badge badge-blue">' + esc(it.category || 'item') + '</span>';
                invHtml += '<span style="flex:1;font-size:0.85rem;color:var(--text-secondary)" title="' + esc(desc) + '">' + esc(it.name) + '</span>';
                if (it.quantity > 1) invHtml += '<span style="font-size:0.78rem;color:var(--text-muted)">x' + it.quantity + '</span>';
                if (truncDesc) invHtml += '<span class="badge badge-purple" title="' + esc(desc) + '">' + esc(truncDesc) + '</span>';
                invHtml += '<button data-item="' + esc(it.name) + '" onclick="N.Features.Overview.openEditItemModal(this.dataset.item)" style="padding:2px 8px;border-radius:4px;border:1px solid rgba(var(--accent-blue-rgb), 0.3);background:rgba(var(--accent-blue-rgb), 0.08);color:var(--accent-blue);cursor:pointer;font-size:0.78rem" title="Edit item"><i data-lucide="pencil"></i></button>';
                invHtml += '<button data-item="' + esc(it.name) + '" onclick="N.Features.Overview.deleteItem(this.dataset.item)" style="padding:2px 8px;border-radius:4px;border:1px solid rgba(255,100,100,0.3);background:rgba(255,100,100,0.08);color:#f87171;cursor:pointer;font-size:0.78rem" title="Delete item"><i data-lucide="trash-2"></i></button>';
                invHtml += '</div>';
            });
            invHtml += '</div>';
        }

        // --- Recent memories grouped by date (for 7-day chart) ---
        const recent = data.recent || [];
        const dayMap = {};
        const now = new Date();
        for (let i = 6; i >= 0; i--) {
            const d = new Date(now); d.setDate(d.getDate() - i);
            dayMap[d.toISOString().slice(0,10)] = 0;
        }
        recent.forEach(m => {
            const d = (m.created_at || '').slice(0,10);
            if (d in dayMap) dayMap[d]++;
        });
        // Augment with stats if available
        if (stats.daily_counts) {
            Object.entries(stats.daily_counts).forEach(([d, c]) => { if (d in dayMap) dayMap[d] = c; });
        }
        const dayLabels = Object.keys(dayMap).map(d => fmtDate(d));
        const dayCounts = Object.values(dayMap);

        // --- Render (new section order) ---
        safeSetHTML(el, `
        <!-- Hero: portrait + status panel -->
        <div class="ov-hero">
            <div id="hero-portrait-slot"></div>
            <div class="ov-status-panel">
                <!-- Quick Status -->
                <div class="ov-quick">
                    <div class="ov-section-title"><i data-lucide="user"></i> Status</div>
                    ${(function(){
                        var emoColor = N.Core.EMOTION_COLORS[ctx.emotion] || N.Core.EMOTION_COLORS.neutral;
                        var pct = Math.round((ctx.emotion_intensity || 0) * 100);
                        return '<div class="ov-emotion-section" style="border-color:' + emoColor + '44">'
                            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
                            + '<span style="font-size:0.9rem;font-weight:700;color:' + emoColor + '">' + esc(ctx.emotion || 'neutral') + '</span>'
                            + '<span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">' + pct + '%</span>'
                            + '</div>'
                            + '<div class="ov-emotion-bar-wrap"><div class="ov-emotion-bar-fill" style="width:' + pct + '%;background:' + (N.Core.EMOTION_BAR_COLORS[ctx.emotion] || N.Core.EMOTION_BAR_COLORS.neutral) + '"></div></div>'
                            + '</div>';
                    })()}
                    <div class="ov-quick-row"><span class="ov-quick-label">Relationship</span><span class="ov-quick-value" style="color:var(--accent-pink);font-weight:600">${esc(relStatus)}</span></div>
                    ${ctx.last_conversation_time ? '<div class="ov-quick-row"><span class="ov-quick-label"><i data-lucide="clock"></i> Last</span><span class="ov-quick-value">' + relativeTime(ctx.last_conversation_time) + '</span></div>' : ''}
                    <div class="ov-quick-row"><span class="ov-quick-label">Physical</span><span class="ov-quick-value">${esc(physicalContent || '--')}</span></div>
                    <div class="ov-quick-row"><span class="ov-quick-label">Mental</span><span class="ov-quick-value">${esc(mentalContent || '--')}</span></div>
                    ${stats.environment ? '<div class="ov-quick-row"><span class="ov-quick-label">Environment</span><span class="ov-quick-value"><span class="badge badge-blue">' + esc(stats.environment) + '</span></span></div>' : ''}
                </div>

                <!-- Memory Stats -->
                <div class="glass p-4" style="border-radius:var(--radius-md);backdrop-filter:blur(20px) saturate(180%)">
                    <div class="ov-section-title"><i data-lucide="bar-chart-3"></i> Memory</div>
                    <div class="ov-stats-grid">
                        <div class="ov-stat-card"><div class="stat-value">${stats.total_count ?? '--'}</div><div class="stat-label">Total</div></div>
                        <div class="ov-stat-card"><div class="stat-value" style="color:var(--accent-green)">${str.avg ?? '--'}</div><div class="stat-label">Avg Strength</div></div>
                        <div class="ov-stat-card"><div class="stat-value" style="color:var(--accent-blue)">${stats.tagged_ratio != null ? (stats.tagged_ratio * 100).toFixed(1) + '%' : '--'}</div><div class="stat-label">Tagged</div></div>
                        <div class="ov-stat-card"><div class="stat-value" style="color:var(--accent-yellow)">${stats.linked_ratio != null ? (stats.linked_ratio * 100).toFixed(1) + '%' : '--'}</div><div class="stat-label">Linked</div></div>
                    </div>
                    ${topTags.length ? '<div style="margin-bottom:6px">' + topTags.map(([t,c]) => '<span class="badge badge-purple">' + esc(t) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join(' ') + '</div>' : ''}
                    ${hasMemTypes ? '<div style="margin-bottom:6px">' + Object.entries(memTypeCounts).map(([t,c]) => '<span class="badge ' + MEMORY_TYPES[t].color + '">' + MEMORY_TYPES[t].icon + ' ' + esc(t) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join(' ') + '</div>' : ''}
                    ${topEmo.length ? '<div>' + topEmo.map(([e,c]) => '<span class="badge badge-pink">' + esc(e) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join(' ') + '</div>' : ''}
                </div>

                <!-- Body Sensations -->
                <div class="glass p-4" style="border-radius:var(--radius-md);backdrop-filter:blur(20px) saturate(180%)">
                    <div class="ov-section-title"><i data-lucide="activity"></i> Body</div>
                    <div class="ov-body-grid">
                        ${(['fatigue','warmth','arousal','heart_rate','pain']).map(k => {
                            var val = stats[k];
                            var label = N.Core.BODY_LABELS[k] || k;
                            var barColor = N.Core.BODY_BAR_COLORS[k] || 'var(--text-muted)';
                            if (val != null) {
                                return '<div>'
                                    + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">'
                                    + '<span style="font-size:0.72rem;color:var(--text-muted)">' + label + '</span>'
                                    + '<span style="font-size:0.72rem;color:var(--text-secondary);font-weight:600">' + (val * 100).toFixed(0) + '%</span>'
                                    + '</div>'
                                    + '<div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden">'
                                    + '<div style="height:100%;width:' + (val * 100).toFixed(1) + '%;background:' + barColor + ';border-radius:2px;transition:width 0.4s ease"></div>'
                                    + '</div></div>';
                            } else {
                                return '<div><span style="font-size:0.72rem;color:var(--text-muted)">' + label + '</span> <span style="font-size:0.72rem;color:var(--text-muted)">--</span></div>';
                            }
                        }).join('')}
                    </div>
                </div>

                <!-- Profile Info -->
                <div class="glass p-4" style="border-radius:var(--radius-md);backdrop-filter:blur(20px) saturate(180%)">
                    <div class="ov-section-title"><i data-lucide="user-circle"></i> Profile</div>
                    ${Object.entries(userInfo).length ? Object.entries(userInfo).map(([k,v]) => '<div class="ov-quick-row"><span class="ov-quick-label">' + esc(k.replace(/_/g,' ')) + '</span><span class="ov-quick-value">' + esc(String(v)) + '</span></div>').join('') : '<span style="color:var(--text-muted);font-size:0.82rem">No user info</span>'}
                    ${(() => { const _GOALS_KEYS = new Set(['goals','active_promises','current_goals']); const filtered = Object.entries(personaInfo).filter(([k]) => !_GOALS_KEYS.has(k)); return filtered.length ? filtered.map(([k,v]) => '<div class="ov-quick-row"><span class="ov-quick-label">' + esc(k.replace(/_/g,' ')) + '</span><span class="ov-quick-value" style="color:var(--accent-purple)">' + esc(String(v)) + '</span></div>').join('') : '<span style="color:var(--text-muted);font-size:0.8rem">No persona info</span>'; })()}
                </div>
            </div>
        </div>

        <!-- Goals -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="target"></i> Goals</div>
            <div>
                <div style="font-size:0.8rem;font-weight:600;color:var(--accent-green);margin-bottom:8px">Goals <span style="opacity:0.6;font-weight:400">(${effectiveGoals.length}件)</span></div>
                <div style="max-height:240px;overflow-y:auto;padding-right:4px">${renderGoalItems(effectiveGoals, 'goals')}</div>
            </div>
        </div>
        <!-- Equipment -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="shield"></i> Equipment</div>
            ${equipHtml}
        </div>
        <!-- Core Memory Blocks -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title" style="justify-content:space-between">
                <span>&#129504; Core Memory Blocks</span>
                <button onclick="N.Features.Overview.showCreateBlock()" class="glass-btn" style="padding:4px 12px;font-size:0.78rem"><i data-lucide="plus"></i> New Block</button>
            </div>
            ${blocksHtml}
        </div>
        <!-- Relationship Highlights (from memory tags) -->
        ${data.relationship_highlights && data.relationship_highlights.length > 0 ? `
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="heart"></i> Relationship Highlights</div>
            <div style="max-height:200px;overflow-y:auto">
            ${data.relationship_highlights.map(h => `
                <div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.82rem;color:var(--text-secondary)">
                    <span style="color:var(--accent-pink);margin-right:6px"><i data-lucide="message-circle"></i></span>${esc(h.content || h)}
                </div>
            `).join('')}
            </div>
        </div>` : ''}
        <!-- Inventory -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
                <div class="card-title" style="margin-bottom:0"><i data-lucide="backpack"></i> Inventory</div>
                <button onclick="N.Features.Overview.openAddItemModal()" style="padding:4px 14px;border-radius:6px;border:1px solid rgba(var(--accent-blue-rgb), 0.4);background:rgba(var(--accent-blue-rgb), 0.1);color:var(--accent-blue);cursor:pointer;font-size:0.82rem;font-weight:600">+ Add Item</button>
            </div>
            ${invHtml}
        </div>
        <!-- Charts -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="glass p-6">
                <div class="card-title"><i data-lucide="calendar"></i> 7-Day Timeline</div>
                <div style="height:220px;position:relative"><canvas id="chart-timeline"></canvas></div>
            </div>
            <div class="glass p-6">
                <div class="card-title"><i data-lucide="tag"></i> Tag Distribution</div>
                <div style="height:220px;position:relative"><canvas id="chart-tags"></canvas></div>
            </div>
        </div>
        <!-- Add Item Modal -->
        <div id="add-item-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;align-items:center;justify-content:center">
            <div style="background:#1e1b2e;border:1px solid rgba(var(--accent-blue-rgb), 0.3);border-radius:14px;padding:28px;width:420px;max-width:92vw;box-shadow:0 24px 64px rgba(0,0,0,0.6)">
                <div style="font-weight:700;font-size:1.05rem;margin-bottom:18px;color:var(--accent-purple)"><i data-lucide="plus"></i> Add Inventory Item</div>
                <div style="display:flex;flex-direction:column;gap:12px">
                    <input id="new-item-name" type="text" placeholder="Item name *" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <input id="new-item-category" type="text" placeholder="Category (e.g. clothing, weapon)" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <input id="new-item-desc" type="text" placeholder="Description" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <input id="new-item-qty" type="number" value="1" min="1" placeholder="Quantity" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                </div>
                <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:20px">
                    <button onclick="N.Features.Overview.closeAddItemModal()" style="padding:7px 18px;border-radius:7px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer;font-size:0.88rem">Cancel</button>
                    <button onclick="N.Features.Overview.saveNewItem()" style="padding:7px 18px;border-radius:7px;border:1px solid rgba(var(--accent-blue-rgb), 0.5);background:rgba(var(--accent-blue-rgb), 0.2);color:var(--accent-blue);cursor:pointer;font-size:0.88rem;font-weight:600">Save</button>
                </div>
            </div>
        </div>
        <!-- Edit Item Modal -->
        <div id="edit-item-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:1000;align-items:center;justify-content:center">
            <div style="background:#1e1b2e;border:1px solid rgba(var(--accent-blue-rgb), 0.3);border-radius:14px;padding:28px;width:420px;max-width:92vw;box-shadow:0 24px 64px rgba(0,0,0,0.6)">
                <div style="font-weight:700;font-size:1.05rem;margin-bottom:18px;color:var(--accent-purple)"><i data-lucide="pencil"></i> Edit Inventory Item</div>
                <input type="hidden" id="edit-item-original-name" value="">
                <div style="display:flex;flex-direction:column;gap:12px">
                    <input id="edit-item-name" type="text" placeholder="Item name *" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <input id="edit-item-category" type="text" placeholder="Category (e.g. clothing, weapon)" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <textarea id="edit-item-desc" placeholder="Description" rows="2" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box;resize:vertical"></textarea>
                    <input id="edit-item-qty" type="number" value="1" min="1" placeholder="Quantity" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                    <input id="edit-item-tags" type="text" placeholder="Tags (comma-separated)" style="width:100%;padding:8px 12px;border-radius:7px;border:1px solid rgba(255,255,255,0.15);background:rgba(255,255,255,0.07);color:var(--text-primary);font-size:0.88rem;outline:none;box-sizing:border-box">
                </div>
                <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:20px">
                    <button onclick="N.Features.Overview.closeEditItemModal()" style="padding:7px 18px;border-radius:7px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer;font-size:0.88rem">Cancel</button>
                    <button onclick="N.Features.Overview.saveEditItem()" style="padding:7px 18px;border-radius:7px;border:1px solid rgba(var(--accent-blue-rgb), 0.5);background:rgba(var(--accent-blue-rgb), 0.2);color:var(--accent-blue);cursor:pointer;font-size:0.88rem;font-weight:600">Save</button>
                </div>
            </div>
        </div>
        <!-- Block Edit Modal -->
        <div id="block-edit-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.6);backdrop-filter:blur(8px);z-index:1000;align-items:center;justify-content:center">
            <div class="glass p-6" style="max-width:500px;width:90%;border-radius:16px;max-height:80vh;overflow-y:auto">
                <h3 style="font-size:1.2rem;font-weight:600;color:var(--text-primary);margin-bottom:16px">
                    <span id="block-modal-title"><i data-lucide="pencil"></i> New Block</span></h3>
                <input type="hidden" id="block-modal-mode" value="create">
                <div style="margin-bottom:12px">
                    <label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Block Name</label>
                    <input type="text" id="block-modal-name" class="glass-input" style="width:100%;padding:8px 12px;box-sizing:border-box" placeholder="e.g. system_notes">
                </div>
                <div style="margin-bottom:12px">
                    <label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Content</label>
                    <textarea id="block-modal-content" class="glass-input" rows="6" style="width:100%;padding:8px 12px;box-sizing:border-box;resize:vertical"></textarea>
                </div>
                <div style="margin-bottom:16px">
                    <label style="display:block;font-size:0.85rem;color:var(--text-muted);margin-bottom:4px">Priority (0-100)</label>
                    <input type="number" id="block-modal-priority" class="glass-input" style="width:100%;padding:8px 12px;box-sizing:border-box" value="0" min="0" max="100">
                </div>
                <div style="display:flex;gap:12px;justify-content:flex-end">
                    <button onclick="N.Features.Overview.hideBlockModal()" class="glass-btn" style="padding:8px 20px">Cancel</button>
                    <button onclick="N.Features.Overview.saveBlock()" class="glass-btn" style="padding:8px 20px;background:var(--accent);color:white">Save</button>
                </div>
            </div>
        </div>`);

        // --- Move portrait into hero slot ---
        var heroSlot = document.getElementById('hero-portrait-slot');
        var portraitEl2 = document.getElementById('overview-portrait');
        if (heroSlot && portraitEl2 && portraitEl2.style.display !== 'none') {
            heroSlot.innerHTML = portraitEl2.innerHTML;
            portraitEl2.style.display = 'none';
        }

        // --- Charts ---
        N.Components.chart.destroy('chart-timeline');
        N.Components.chart.destroy('chart-tags');
        const tlCtx = document.getElementById('chart-timeline');
        if (tlCtx) {
            S.charts['chart-timeline'] = new Chart(tlCtx, {
                type: 'bar',
                data: { labels: dayLabels, datasets: [{ label: 'Memories', data: dayCounts, backgroundColor: 'rgba(0,122,255,0.5)', borderColor: '#007aff', borderWidth: 1, borderRadius: 6 }] },
                options: N.Components.chart.defaults({ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } }, x: {} } })
            });
        }
        const allTags = Object.entries(tagDist).sort((a,b) => b[1]-a[1]).slice(0, 8);
        const tgCtx = document.getElementById('chart-tags');
        if (tgCtx && allTags.length) {
            S.charts['chart-tags'] = new Chart(tgCtx, {
                type: 'doughnut',
                data: { labels: allTags.map(t=>t[0]), datasets: [{ data: allTags.map(t=>t[1]), backgroundColor: N.Core.CHART_COLORS.slice(0, allTags.length), borderWidth: 0 }] },
                options: { ...N.Components.chart.defaults(), cutout: '60%' }
            });
        } else if (tgCtx) {
            tgCtx.parentElement.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:200px;color:var(--text-muted);font-size:0.85rem;">タグがありません</div>';
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        console.error('overview load failed:', e);
        safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load dashboard stats', function(){ loadOverview(); }));
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}
/* N.Features.Overview.loadOverview registered below */

// Register in namespace (CRUD helpers live in overview-blocks.js / overview-inventory.js)
Object.assign(N.Features.Overview, {
    loadOverview: loadOverview,
});
})();
