;(function() {
var S = window.S;
var { esc, toast, api, truncate, relativeTime, fmtDate } = window.Nous.Core;

// --- Block CRUD helpers (global scope) ---
function showCreateBlock() {
    document.getElementById('block-modal-title').innerHTML = '<i data-lucide="pencil"></i> New Block';
    document.getElementById('block-modal-mode').value = 'create';
    document.getElementById('block-modal-name').value = '';
    document.getElementById('block-modal-name').disabled = false;
    document.getElementById('block-modal-content').value = '';
    document.getElementById('block-modal-priority').value = '0';
    document.getElementById('block-edit-modal').style.display = 'flex';
}
window.showCreateBlock = showCreateBlock;

function showEditBlock(name, content, priority) {
    document.getElementById('block-modal-title').innerHTML = '<i data-lucide="pencil"></i> Edit Block: ' + esc(name);
    document.getElementById('block-modal-mode').value = 'edit';
    document.getElementById('block-modal-name').value = name;
    document.getElementById('block-modal-name').disabled = true;
    document.getElementById('block-modal-content').value = content || '';
    document.getElementById('block-modal-priority').value = priority || 0;
    document.getElementById('block-edit-modal').style.display = 'flex';
}
window.showEditBlock = showEditBlock;

function hideBlockModal() {
    document.getElementById('block-edit-modal').style.display = 'none';
}
window.hideBlockModal = hideBlockModal;

async function saveBlock() {
    var name = document.getElementById('block-modal-name').value.trim();
    var content = document.getElementById('block-modal-content').value.trim();
    var priority = parseInt(document.getElementById('block-modal-priority').value) || 0;
    if (!name || !content) { toast('Block name and content required', 'error'); return; }
    try {
        await api('/api/blocks/' + encodeURIComponent(S.persona), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({block_name: name, content: content, priority: priority})
        });
        hideBlockModal();
        toast('Block saved!', 'success');
        loadOverview();
    } catch (e) { toast('Failed to save block: ' + e.message, 'error'); }
}
window.saveBlock = saveBlock;

async function deleteBlock(name) {
    if (!confirm('Delete block "' + name + '"?')) return;
    try {
        await api('/api/blocks/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(name), {method: 'DELETE'});
        toast('Block deleted', 'success');
        loadOverview();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
window.deleteBlock = deleteBlock;

// --- Inventory CRUD helpers (global scope) ---
async function deleteItem(itemName) {
    if (!confirm('Delete item: ' + itemName + '?')) return;
    try {
        await api('/api/items/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(itemName), {method:'DELETE'});
        loadOverview();
    } catch (e) {
        toast('Failed to delete item: ' + e.message, 'error');
    }
}
window.deleteItem = deleteItem;

function openAddItemModal() {
    const m = document.getElementById('add-item-modal');
    if (m) { m.style.display = 'flex'; }
}
window.openAddItemModal = openAddItemModal;

function closeAddItemModal() {
    const m = document.getElementById('add-item-modal');
    if (m) { m.style.display = 'none'; }
    ['new-item-name','new-item-category','new-item-desc','new-item-qty'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = id === 'new-item-qty' ? '1' : '';
    });
}
window.closeAddItemModal = closeAddItemModal;

async function saveNewItem() {
    const nameEl = document.getElementById('new-item-name');
    const name = (nameEl ? nameEl.value : '').trim();
    if (!name) { toast('Item name is required', 'error'); return; }
    const category = (document.getElementById('new-item-category') || {}).value || '';
    const desc = (document.getElementById('new-item-desc') || {}).value || '';
    const qty = parseInt((document.getElementById('new-item-qty') || {}).value || '1', 10) || 1;
    try {
        await api('/api/items/' + encodeURIComponent(S.persona), {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({item_name: name, category: category || null, description: desc || null, quantity: qty})
        });
        closeAddItemModal();
        loadOverview();
    } catch (e) {
        toast('Failed to add item: ' + e.message, 'error');
    }
}
window.saveNewItem = saveNewItem;

// --- Edit item ---
function openEditItemModal(itemName) {
    var item = null;
    if (S.dashCache && S.dashCache.items) {
        var items = S.dashCache.items;
        for (var i = 0; i < items.length; i++) {
            if (items[i].name === itemName) { item = items[i]; break; }
        }
    }
    if (!item) { toast('Item not found in cache', 'error'); return; }
    document.getElementById('edit-item-original-name').value = itemName;
    document.getElementById('edit-item-name').value = item.name || '';
    document.getElementById('edit-item-category').value = item.category || '';
    document.getElementById('edit-item-desc').value = item.description || '';
    document.getElementById('edit-item-qty').value = item.quantity || 1;
    document.getElementById('edit-item-tags').value = (item.tags || []).join(', ');
    document.getElementById('edit-item-modal').style.display = 'flex';
}
window.openEditItemModal = openEditItemModal;

function closeEditItemModal() {
    document.getElementById('edit-item-modal').style.display = 'none';
}
window.closeEditItemModal = closeEditItemModal;

async function saveEditItem() {
    var originalName = document.getElementById('edit-item-original-name').value;
    var name = document.getElementById('edit-item-name').value.trim();
    var category = document.getElementById('edit-item-category').value.trim() || null;
    var description = document.getElementById('edit-item-desc').value.trim() || null;
    var qty = parseInt(document.getElementById('edit-item-qty').value, 10) || 1;
    var tagsStr = document.getElementById('edit-item-tags').value.trim();
    var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];
    if (!name) { toast('Item name is required', 'error'); return; }
    try {
        await api('/api/items/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(originalName), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                item_name: name,
                category: category,
                description: description,
                quantity: qty,
                tags: tags
            })
        });
        closeEditItemModal();
        toast('Item updated!', 'success');
        loadOverview();
    } catch (e) {
        toast('Failed to update item: ' + e.message, 'error');
    }
}
window.saveEditItem = saveEditItem;

async function changeEquipSlot(slot, itemName) {
    try {
        const body = {};
        body[slot] = itemName;
        await api('/api/items/' + encodeURIComponent(S.persona) + '/equip', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(body)
        });
        loadOverview();
    } catch (e) {
        toast('Failed to change equipment: ' + e.message, 'error');
    }
}
window.changeEquipSlot = changeEquipSlot;

async function unequipSlot(slot) {
    try {
        await api('/api/items/' + encodeURIComponent(S.persona) + '/unequip', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({slots: [slot]})
        });
        loadOverview();
    } catch (e) {
        toast('Failed to unequip: ' + e.message, 'error');
    }
}
window.unequipSlot = unequipSlot;

async function loadOverview() {
    const el = document.getElementById('overview-content');
    try {
        const data = await api('/api/dashboard/' + encodeURIComponent(S.persona));
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
                equipHtml += '<button data-slot="' + esc(slot) + '" onclick="unequipSlot(this.dataset.slot)" style="font-size:0.72rem;padding:2px 8px;border-radius:4px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer" title="Unequip"><i data-lucide="x"></i></button>';
            } else {
                equipHtml += '<span style="flex:1;font-size:0.82rem;color:var(--text-muted);font-style:italic">empty</span>';
                const slotItems = items.filter(it => it.name);
                if (slotItems.length > 0) {
                    equipHtml += '<select data-slot="' + esc(slot) + '" onchange="if(this.value) changeEquipSlot(this.dataset.slot, this.value)" style="font-size:0.78rem;background:var(--glass-bg);border:1px solid var(--glass-border);border-radius:4px;color:var(--text-secondary);padding:2px 4px"><option value="">equip...</option>';
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
                blocksHtml += '<button class="glass-btn" data-bname="' + esc(name) + '" data-bcontent="' + esc(content) + '" data-bpriority="' + (priority || 0) + '" onclick="var el=this;showEditBlock(el.dataset.bname,el.dataset.bcontent,parseInt(el.dataset.bpriority||0))" style="padding:3px 10px;font-size:0.75rem"><i data-lucide="pencil"></i> Edit</button>';
                blocksHtml += '<button class="glass-btn" data-bname="' + esc(name) + '" onclick="deleteBlock(this.dataset.bname)" style="padding:3px 10px;font-size:0.75rem;color:var(--accent-red)"><i data-lucide="trash-2"></i> Delete</button>';
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
                invHtml += '<button data-item="' + esc(it.name) + '" onclick="openEditItemModal(this.dataset.item)" style="padding:2px 8px;border-radius:4px;border:1px solid rgba(var(--accent-blue-rgb), 0.3);background:rgba(var(--accent-blue-rgb), 0.08);color:var(--accent-blue);cursor:pointer;font-size:0.78rem" title="Edit item"><i data-lucide="pencil"></i></button>';
                invHtml += '<button data-item="' + esc(it.name) + '" onclick="deleteItem(this.dataset.item)" style="padding:2px 8px;border-radius:4px;border:1px solid rgba(255,100,100,0.3);background:rgba(255,100,100,0.08);color:#f87171;cursor:pointer;font-size:0.78rem" title="Delete item"><i data-lucide="trash-2"></i></button>';
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
        el.innerHTML = `
        <!-- Profile & Relationship -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="user"></i> Profile &amp; Relationship</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:8px;font-weight:600">Relationship</div>
                    <div style="font-size:0.9rem;color:var(--accent-pink);font-weight:600;margin-bottom:12px">${esc(relStatus)}</div>
                    ${ctx.last_conversation_time ? `<div style="margin-bottom:12px;display:flex;align-items:center;gap:8px"><span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="clock"></i> Last session:</span><span class="badge badge-blue">${relativeTime(ctx.last_conversation_time)}</span></div>` : ''}
                    <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px;font-weight:600">User Info</div>
                    ${Object.entries(userInfo).length ? Object.entries(userInfo).map(([k,v]) => `<div style="display:flex;gap:8px;padding:4px 0;font-size:0.85rem"><span style="color:var(--text-muted);min-width:120px">${esc(k.replace(/_/g,' '))}</span><span style="color:var(--text-secondary)">${esc(String(v))}</span></div>`).join('') : '<span style="color:var(--text-muted)">No user info</span>'}
                </div>
                <div>
                    <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px;font-weight:600">Persona Info</div>
                    ${(() => { const _GOALS_KEYS = new Set(['goals','active_promises','current_goals']); const filtered = Object.entries(personaInfo).filter(([k]) => !_GOALS_KEYS.has(k)); return filtered.length ? filtered.map(([k,v]) => `<div style="display:flex;gap:8px;padding:4px 0;font-size:0.85rem"><span style="color:var(--text-muted);min-width:120px">${esc(k.replace(/_/g,' '))}</span><span style="color:var(--accent-purple)">${esc(String(v))}</span></div>`).join('') : '<span style="color:var(--text-muted)">No persona info</span>'; })()}
                </div>
            </div>
        </div>
        <!-- Memory Stats -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="bar-chart-3"></i> Memory Stats</div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div><div class="stat-value">${stats.total_count ?? '--'}</div><div class="stat-label">Total Memories</div></div>
                <div><div class="stat-value" style="color:var(--accent-green)">${str.avg ?? '--'}</div><div class="stat-label">Avg Strength</div></div>
                <div><div class="stat-value" style="color:var(--accent-blue)">${stats.tagged_ratio != null ? (stats.tagged_ratio * 100).toFixed(1) + '%' : '--'}</div><div class="stat-label">Tagged</div></div>
                <div><div class="stat-value" style="color:var(--accent-yellow)">${stats.linked_ratio != null ? (stats.linked_ratio * 100).toFixed(1) + '%' : '--'}</div><div class="stat-label">Linked</div></div>
            </div>
            <div style="margin-bottom:10px">
                <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px">Top Tags</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px">${topTags.length ? topTags.map(([t,c]) => '<span class="badge badge-purple">' + esc(t) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join('') : '<span style="color:var(--text-muted)">--</span>'}</div>
            </div>
            ${hasMemTypes ? `<div style="margin-bottom:10px">
                <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px">Memory Types</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px">${Object.entries(memTypeCounts).map(([t,c]) => '<span class="badge ' + MEMORY_TYPES[t].color + '">' + MEMORY_TYPES[t].icon + ' ' + esc(t) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join('')}</div>
            </div>` : ''}
            <div>
                <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:6px">Top Emotions</div>
                <div style="display:flex;flex-wrap:wrap;gap:6px">${topEmo.length ? topEmo.map(([e,c]) => '<span class="badge badge-pink">' + esc(e) + ' <span style="opacity:0.7">(' + c + ')</span></span>').join('') : '<span style="color:var(--text-muted)">--</span>'}</div>
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
        <!-- Emotion -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="sparkles"></i> Emotion</div>
            <div>
                ${(function() {
                    /* Constants now from core/constants.js via adapter globals */
                    if (ctx.emotion) {
                        var barGrad = window.EMOTION_BAR_COLORS[ctx.emotion] || window.EMOTION_BAR_COLORS.neutral;
                        var pct = (ctx.emotion_intensity || 0) * 100;
                        pct = Math.round(pct);
                        return '<div style="margin-bottom:12px">' +
                            '<div style="margin-bottom:8px">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">' +
                            '<span style="font-size:0.78rem;color:var(--text-muted)">' + esc(ctx.emotion) + '</span>' +
                            '<span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">' + pct + '%</span>' +
                            '</div>' +
                            '<div style="height:5px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">' +
                            '<div style="height:100%;width:' + pct + '%;background:' + barGrad + ';border-radius:3px;transition:width 0.4s ease"></div>' +
                            '</div>' +
                            '</div></div>';
                    }
                    return '<div style="font-size:0.9rem;color:var(--text-muted);margin-bottom:12px">--</div>';
                })()}
                <div style="display:flex;flex-direction:column;gap:6px">
                    <div><span style="font-size:0.78rem;color:var(--text-muted)">Physical: </span><span style="font-size:0.85rem">${esc(physicalContent || '--')}</span></div>
                    <div><span style="font-size:0.78rem;color:var(--text-muted)">Mental: </span><span style="font-size:0.85rem">${esc(mentalContent || '--')}</span></div>
                    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span style="font-size:0.78rem;color:var(--text-muted);min-width:78px"><i data-lucide="globe"></i> Env:</span>${stats.environment ? '<span class="badge badge-blue">' + esc(stats.environment) + '</span>' : '<span style="color:var(--text-muted);font-size:0.82rem">--</span>'}</div>
                </div>
            </div>
        </div>
        <!-- Equipment -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="shield"></i> Equipment</div>
            ${equipHtml}
        </div>
        <!-- Body Sensations -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title"><i data-lucide="activity"></i> Body Sensations</div>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
                        <span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="flame"></i> Fatigue</span>
                        <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">${stats.fatigue != null ? (stats.fatigue * 100).toFixed(0) + '%' : '--'}</span>
                    </div>
                    <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${stats.fatigue != null ? (stats.fatigue * 100).toFixed(1) : 0}%;background:${window.BODY_BAR_COLORS.fatigue};border-radius:3px;transition:width 0.4s ease"></div>
                    </div>
                </div>
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
                        <span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="flower"></i> Warmth</span>
                        <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">${stats.warmth != null ? (stats.warmth * 100).toFixed(0) + '%' : '--'}</span>
                    </div>
                    <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${stats.warmth != null ? (stats.warmth * 100).toFixed(1) : 0}%;background:${window.BODY_BAR_COLORS.warmth};border-radius:3px;transition:width 0.4s ease"></div>
                    </div>
                </div>
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
                        <span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="zap"></i> Arousal</span>
                        <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">${stats.arousal != null ? (stats.arousal * 100).toFixed(0) + '%' : '--'}</span>
                    </div>
                    <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${stats.arousal != null ? (stats.arousal * 100).toFixed(1) : 0}%;background:${window.BODY_BAR_COLORS.arousal};border-radius:3px;transition:width 0.4s ease"></div>
                    </div>
                </div>
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
                        <span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="heart-pulse"></i> Heart Rate</span>
                        <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">${stats.heart_rate != null ? (stats.heart_rate * 100).toFixed(0) + '%' : '--'}</span>
                    </div>
                    <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${stats.heart_rate != null ? (stats.heart_rate * 100).toFixed(1) : 0}%;background:${window.BODY_BAR_COLORS.heart_rate};border-radius:3px;transition:width 0.4s ease"></div>
                    </div>
                </div>
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
                        <span style="font-size:0.78rem;color:var(--text-muted)"><i data-lucide="activity"></i> Pain</span>
                        <span style="font-size:0.78rem;color:var(--text-secondary);font-weight:600">${stats.pain != null ? (stats.pain * 100).toFixed(0) + '%' : '--'}</span>
                    </div>
                    <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden">
                        <div style="height:100%;width:${stats.pain != null ? (stats.pain * 100).toFixed(1) : 0}%;background:${window.BODY_BAR_COLORS.pain};border-radius:3px;transition:width 0.4s ease"></div>
                    </div>
                </div>
            </div>
        </div>
        <!-- Core Memory Blocks -->
        <div class="glass glass-hoverable p-6 mb-6">
            <div class="card-title" style="justify-content:space-between">
                <span>&#129504; Core Memory Blocks</span>
                <button onclick="showCreateBlock()" class="glass-btn" style="padding:4px 12px;font-size:0.78rem"><i data-lucide="plus"></i> New Block</button>
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
                <button onclick="openAddItemModal()" style="padding:4px 14px;border-radius:6px;border:1px solid rgba(var(--accent-blue-rgb), 0.4);background:rgba(var(--accent-blue-rgb), 0.1);color:var(--accent-blue);cursor:pointer;font-size:0.82rem;font-weight:600">+ Add Item</button>
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
                    <button onclick="closeAddItemModal()" style="padding:7px 18px;border-radius:7px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer;font-size:0.88rem">Cancel</button>
                    <button onclick="saveNewItem()" style="padding:7px 18px;border-radius:7px;border:1px solid rgba(var(--accent-blue-rgb), 0.5);background:rgba(var(--accent-blue-rgb), 0.2);color:var(--accent-blue);cursor:pointer;font-size:0.88rem;font-weight:600">Save</button>
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
                    <button onclick="closeEditItemModal()" style="padding:7px 18px;border-radius:7px;border:1px solid var(--glass-border);background:var(--glass-bg);color:var(--text-muted);cursor:pointer;font-size:0.88rem">Cancel</button>
                    <button onclick="saveEditItem()" style="padding:7px 18px;border-radius:7px;border:1px solid rgba(var(--accent-blue-rgb), 0.5);background:rgba(var(--accent-blue-rgb), 0.2);color:var(--accent-blue);cursor:pointer;font-size:0.88rem;font-weight:600">Save</button>
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
                    <button onclick="hideBlockModal()" class="glass-btn" style="padding:8px 20px">Cancel</button>
                    <button onclick="saveBlock()" class="glass-btn" style="padding:8px 20px;background:var(--accent);color:white">Save</button>
                </div>
            </div>
        </div>`;

        // --- Charts ---
        destroyChart('chart-timeline');
        destroyChart('chart-tags');
        const tlCtx = document.getElementById('chart-timeline');
        if (tlCtx) {
            S.charts['chart-timeline'] = new Chart(tlCtx, {
                type: 'bar',
                data: { labels: dayLabels, datasets: [{ label: 'Memories', data: dayCounts, backgroundColor: 'rgba(0,122,255,0.5)', borderColor: '#007aff', borderWidth: 1, borderRadius: 6 }] },
                options: chartOpts({ plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } }, x: {} } })
            });
        }
        const allTags = Object.entries(tagDist).sort((a,b) => b[1]-a[1]).slice(0, 8);
        const tgCtx = document.getElementById('chart-tags');
        if (tgCtx && allTags.length) {
            S.charts['chart-tags'] = new Chart(tgCtx, {
                type: 'doughnut',
                data: { labels: allTags.map(t=>t[0]), datasets: [{ data: allTags.map(t=>t[1]), backgroundColor: window.CHART_COLORS.slice(0, allTags.length), borderWidth: 0 }] },
                options: { ...chartOpts(), cutout: '60%' }
            });
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        el.innerHTML = errorCard('Failed to load overview: ' + e.message);
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}
window.loadOverview = loadOverview;
})();