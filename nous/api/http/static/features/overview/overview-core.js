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
        // ── Extract core data early for portrait+params ──
        const stats = data.stats || {};
        const ctx = data.context || {};

        // ── Portrait + Tabbed Persona Status Panel ──
        const portraitUrl = data.latest_self_portrait;
        const portraitEl = document.getElementById('overview-portrait');
        const emoColor = N.Core.EMOTION_COLORS[ctx.emotion] || '#94a3b8';
        const emoIntensityPct = Math.round((ctx.emotion_intensity || 0) * 100);
        const emoBarColor = N.Core.EMOTION_BAR_COLORS[ctx.emotion] || N.Core.EMOTION_BAR_COLORS.neutral || '#94a3b8';

        // State memories for Main tab
        const sm2 = data.state_memories || {};
        const physContent = (sm2.physical_state?.content) || ctx.physical_state || '--';
        const mentContent = (sm2.mental_state?.content) || ctx.mental_state || '--';
        const relStatus = ctx.relationship_status || ctx.relationship_type || '--';

        // Main tab: emotion + states + body metrics
        const mainTabHtml =
            '<div style="margin-bottom:16px">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
            + '<span style="font-size:0.82rem;font-weight:600;color:var(--text-secondary)">' + (ctx.emotion ? esc(ctx.emotion) : 'Emotion') + '</span>'
            + '<span style="font-size:0.82rem;font-weight:600;color:var(--text-muted);font-variant-numeric:tabular-nums">' + (ctx.emotion ? emoIntensityPct + '%' : '--') + '</span>'
            + '</div>'
            + '<div style="height:8px;background:rgba(255,255,255,0.08);border-radius:4px;overflow:hidden">'
            + '<div style="height:100%;width:' + (ctx.emotion ? emoIntensityPct : 0) + '%;background:' + emoBarColor + ';border-radius:4px;transition:width 0.6s cubic-bezier(0.25,0.46,0.45,0.94)"></div>'
            + '</div></div>'
            + '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:16px">'
            + '<div><span style="font-size:0.78rem;color:var(--text-muted)">Physical: </span><span style="font-size:0.85rem;color:var(--text-secondary)">' + esc(physContent) + '</span></div>'
            + '<div><span style="font-size:0.78rem;color:var(--text-muted)">Mental: </span><span style="font-size:0.85rem;color:var(--text-secondary)">' + esc(mentContent) + '</span></div>'
            + '<div><span style="font-size:0.78rem;color:var(--text-muted)">Relationship: </span><span style="font-size:0.85rem;color:var(--accent-pink);font-weight:600">' + esc(relStatus) + '</span></div>'
            + '<div style="display:flex;align-items:center;gap:6px"><span style="font-size:0.78rem;color:var(--text-muted)">Environment: </span>' + (stats.environment ? '<span class="badge badge-blue">' + esc(stats.environment) + '</span>' : '<span style="font-size:0.82rem;color:var(--text-muted)">--</span>') + '</div>'
            + '</div>'
            + '<div style="font-size:0.78rem;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:10px">Body State</div>'
            + '<div style="display:flex;flex-direction:column;gap:10px">'
            + [['fatigue','Fatigue','#f87171'],['warmth','Warmth','#f9a8d4'],['arousal','Arousal','#5856d6'],['heart_rate','Heart Rate','#ef4444'],['pain','Pain','#f59e0b']].map(function(b) {
                var v = stats[b[0]];
                var pct = v != null ? Math.round(v * 100) : 0;
                var label = v != null ? (v * 100).toFixed(0) + '%' : '--';
                return '<div><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">'
                    + '<span style="font-size:0.76rem;color:var(--text-muted)">' + b[1] + '</span>'
                    + '<span style="font-size:0.76rem;color:var(--text-secondary);font-weight:600;font-variant-numeric:tabular-nums">' + label + '</span>'
                    + '</div>'
                    + '<div style="height:5px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">'
                    + '<div style="height:100%;width:' + pct + '%;background:' + b[2] + ';border-radius:3px;transition:width 0.6s cubic-bezier(0.25,0.46,0.45,0.94)"></div>'
                    + '</div></div>';
            }).join('')
            + '</div>';

        // Equipment tab
        var equipTabHtml2 = '';
        if (ctx.equipped_items && ctx.equipped_items.length > 0) {
            equipTabHtml2 = '<div style="display:grid;gap:6px">' + ctx.equipped_items.map(function(item) {
                var name = typeof item === 'string' ? item : (item.name || JSON.stringify(item));
                return '<div style="display:flex;align-items:center;gap:8px;padding:8px;background:var(--glass-bg-subtle);border:1px solid var(--glass-border);border-radius:8px">'
                    + '<span class="badge badge-blue">' + esc(name) + '</span></div>';
            }).join('') + '</div>';
        } else {
            equipTabHtml2 = '<div style="color:var(--text-muted);font-size:0.85rem;padding:12px 0">No equipped items</div>';
        }

        if (portraitEl) {
            portraitEl.style.setProperty('--emo-glow', emoColor);
            portraitEl.style.display = 'grid';
            portraitEl.className = 'ov-portrait-2col';
            var portraitLeftHtml = '';
            if (portraitUrl) {
                portraitLeftHtml = '<div class="ov-portrait-left" onclick="N.Chat.attachments.openViewer(\'' + esc(portraitUrl) + '\',\'image\')">'
                    + '<img src="' + esc(portraitUrl) + '" alt="Self Portrait" class="ov-portrait-img">'
                    + '<div class="ov-portrait-label">Latest Self Portrait</div>'
                    + '</div>';
            } else {
                portraitEl.classList.add('ov-no-portrait');
            }
            safeSetHTML(portraitEl,
                portraitLeftHtml
                + '<div class="ov-params-right">'
                + '<div class="ov-tab-btns">'
                + '<button class="ov-tab-btn active" data-ovtab="main">Main</button>'
                + '<button class="ov-tab-btn" data-ovtab="equipment">Equipment</button>'
                + '</div>'
                + '<div class="ov-tab-panel" id="ov-panel-main">' + mainTabHtml + '</div>'
                + '<div class="ov-tab-panel" id="ov-panel-equipment" style="display:none">' + equipTabHtml2 + '</div>'
                + '</div>'
            );
            // Tab switching for the new panel
            var tabBtns = portraitEl.querySelectorAll('.ov-tab-btn');
            tabBtns.forEach(function(btn) {
                btn.addEventListener('click', function() {
                    tabBtns.forEach(function(b) { b.classList.remove('active'); });
                    btn.classList.add('active');
                    portraitEl.querySelectorAll('.ov-tab-panel').forEach(function(p) { p.style.display = 'none'; });
                    var target = portraitEl.querySelector('#ov-panel-' + btn.dataset.ovtab);
                    if (target) target.style.display = '';
                });
            });
        }

        // ── Generated Images History Grid ──
        const imagesGridEl = document.getElementById('overview-images-grid');
        let generatedImagesHtml = '';
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
                generatedImagesHtml = gridHtml;
                imagesGridEl.style.display = 'none';
            } else {
                imagesGridEl.style.display = 'none';
            }
        }
        S.dashCache = data;

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
        const tagDist = stats.tag_distribution || {};
        const effectiveGoals = data.goals || [];

        // --- Goals HTML ---
        function getStatusIcon(status) {
            if (status === 'active') return '<i data-lucide="refresh-cw"></i>';
            if (status === 'achieved' || status === 'fulfilled') return '<i data-lucide="check-circle"></i>';
            if (status === 'cancelled') return '<i data-lucide="x-circle"></i>';
            return '<i data-lucide="refresh-cw"></i>';
        }
        let goalsHtml = '';
        if (effectiveGoals.length > 0) {
            goalsHtml = '<div style="display:flex;flex-direction:column;gap:4px">' + effectiveGoals.map(function(item) {
                var content = typeof item === 'string' ? item : (item.content || item.description || item.title || JSON.stringify(item));
                var status = typeof item === 'object' ? (item.status || 'active').toLowerCase() : 'active';
                var icon = getStatusIcon(status);
                return '<div style="display:flex;align-items:center;gap:8px;padding:6px 0">'
                    + '<span style="color:var(--accent-green)">' + icon + '</span>'
                    + '<span style="flex:1;font-size:0.85rem;color:var(--text-secondary)">' + esc(content) + '</span></div>';
            }).join('') + '</div>';
        } else {
            goalsHtml = '<span style="color:var(--text-muted)">No goals</span>';
        }

        // Build main HTML
        safeSetHTML(el, `
        <!-- Memory Stats -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="bar-chart-3"></i> Memory Stats</div>
            <div class="ov-stats-grid">
                <div class="ov-stat-card">
                    <div class="ov-stat-value">${stats.total_count ?? '--'}</div>
                    <div class="ov-stat-label">Total Memories</div>
                </div>
                <div class="ov-stat-card">
                    <div class="ov-stat-value" style="color:var(--accent-green)">${((data.strengths || {}).avg ?? '--')}</div>
                    <div class="ov-stat-label">Avg Strength</div>
                </div>
            </div>
        </div>
        <!-- Core Memory Blocks -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title" style="justify-content:space-between">
                <span>&#129504; Core Memory Blocks</span>
                <button onclick="N.Features.Overview.showCreateBlock()" class="glass-btn" style="padding:4px 12px;font-size:0.78rem"><i data-lucide="plus"></i> New Block</button>
            </div>
            ${blocksHtml}
        </div>
        <!-- Goals -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="target"></i> Goals</div>
            ${goalsHtml}
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
        <!-- Generated Images (moved to bottom) -->
        ${generatedImagesHtml}
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
