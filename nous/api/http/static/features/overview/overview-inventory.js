/* =================================================================
   OVERVIEW INVENTORY — Inventory CRUD helpers
   Namespace: N.Features.Overview.*
   Depends on: N.Core.* (esc, toast, api, safeSetHTML)
               overview-core.js (loadOverview)
   ================================================================= */
N.Features.Overview = N.Features.Overview || {};

;(function() {
var S = window.S;
var { esc, toast, api, safeSetHTML } = window.Nous.Core;

async function deleteItem(itemName) {
    if (!confirm('Delete item: ' + itemName + '?')) return;
    try {
        await api('/api/items/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(itemName), {method:'DELETE'});
        N.Features.Overview.loadOverview();
    } catch (e) {
        toast('Failed to delete item: ' + e.message, 'error');
    }
}

function openAddItemModal() {
    const m = document.getElementById('add-item-modal');
    if (m) { m.classList.add('active'); }
}

function closeAddItemModal() {
    const m = document.getElementById('add-item-modal');
    if (m) { m.classList.remove('active'); }
    ['new-item-name','new-item-category','new-item-desc','new-item-qty'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = id === 'new-item-qty' ? '1' : '';
    });
}

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
        N.Features.Overview.loadOverview();
    } catch (e) {
        toast('Failed to add item: ' + e.message, 'error');
    }
}

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
    document.getElementById('edit-item-modal').classList.add('active');
}

function closeEditItemModal() {
    document.getElementById('edit-item-modal').classList.remove('active');
}

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
        N.Features.Overview.loadOverview();
    } catch (e) {
        toast('Failed to update item: ' + e.message, 'error');
    }
}

async function changeEquipSlot(slot, itemName) {
    try {
        const body = {};
        body[slot] = itemName;
        await api('/api/items/' + encodeURIComponent(S.persona) + '/equip', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(body)
        });
        N.Features.Overview.loadOverview();
    } catch (e) {
        toast('Failed to change equipment: ' + e.message, 'error');
    }
}

async function unequipSlot(slot) {
    try {
        await api('/api/items/' + encodeURIComponent(S.persona) + '/unequip', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({slots: [slot]})
        });
        N.Features.Overview.loadOverview();
    } catch (e) {
        toast('Failed to unequip: ' + e.message, 'error');
    }
}

Object.assign(N.Features.Overview, {
    deleteItem: deleteItem,
    openAddItemModal: openAddItemModal,
    closeAddItemModal: closeAddItemModal,
    saveNewItem: saveNewItem,
    openEditItemModal: openEditItemModal,
    closeEditItemModal: closeEditItemModal,
    saveEditItem: saveEditItem,
    changeEquipSlot: changeEquipSlot,
    unequipSlot: unequipSlot,
});
})();
