/* =================================================================
   OVERVIEW BLOCKS — Block CRUD helpers
   Namespace: N.Features.Overview.*
   Depends on: N.Core.* (esc, toast, api, safeSetHTML)
               overview-core.js (loadOverview)
   ================================================================= */
N.Features.Overview = N.Features.Overview || {};

;(function() {
var S = window.S;
var { esc, toast, api, truncate, safeSetHTML } = window.Nous.Core;

function showCreateBlock() {
    safeSetHTML(document.getElementById('block-modal-title'), '<i data-lucide="pencil"></i> New Block');
    document.getElementById('block-modal-mode').value = 'create';
    document.getElementById('block-modal-name').value = '';
    document.getElementById('block-modal-name').disabled = false;
    document.getElementById('block-modal-content').value = '';
    document.getElementById('block-modal-priority').value = '0';
    document.getElementById('block-edit-modal').classList.add('active');
}

function showEditBlock(name, content, priority) {
    safeSetHTML(document.getElementById('block-modal-title'), '<i data-lucide="pencil"></i> Edit Block: ' + esc(name));
    document.getElementById('block-modal-mode').value = 'edit';
    document.getElementById('block-modal-name').value = name;
    document.getElementById('block-modal-name').disabled = true;
    document.getElementById('block-modal-content').value = content || '';
    document.getElementById('block-modal-priority').value = priority || 0;
    document.getElementById('block-edit-modal').classList.add('active');
}

function hideBlockModal() {
    document.getElementById('block-edit-modal').classList.remove('active');
}

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
        N.Features.Overview.loadOverview();
    } catch (e) { toast('Failed to save block: ' + e.message, 'error'); }
}

async function deleteBlock(name) {
    if (!confirm('Delete block "' + name + '"?')) return;
    try {
        await api('/api/blocks/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(name), {method: 'DELETE'});
        toast('Block deleted', 'success');
        N.Features.Overview.loadOverview();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

Object.assign(N.Features.Overview, {
    showCreateBlock: showCreateBlock,
    showEditBlock: showEditBlock,
    hideBlockModal: hideBlockModal,
    saveBlock: saveBlock,
    deleteBlock: deleteBlock,
});
})();
