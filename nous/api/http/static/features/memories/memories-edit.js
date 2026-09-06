/* =================================================================
   MEMORIES EDIT — Edit/create forms, save/delete
   Namespace: N.Features.Memories.*
   The memory DETAIL modal lives in components/mem-modal.js
   (N.Components.memModal) — the shared view for all tabs. The three
   functions below are thin wrappers kept so existing callers
   (memories-core.js, graph.js, base.js) keep working.
   Depends on: N.Core.* (api, esc, toast, showConfirm)
                N.Components.memModal, window.S, window.safeSetHTML
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;
var { esc, toast, api, showConfirm, safeSetHTML } = window.Nous.Core;

/* ================================================================
   Thin wrappers — real implementation in components/mem-modal.js
   ================================================================ */
async function openMemModalByKey(key) {
    return N.Components.memModal.open(key);
}
async function openMemModal(mem) {
    return N.Components.memModal.openMemory(mem);
}
function closeMemModal() {
    return N.Components.memModal.close();
}

/* ================================================================
   openEditModal / openCreateModal
   ================================================================ */
var _editTags = [];

function _renderEditTags() {
    var wrap = document.getElementById('edit-tags-wrap');
    if (!wrap) return;
    var chips = wrap.querySelectorAll('.tag-chip-edit');
    chips.forEach(function(c){ c.remove(); });
    var inp = document.getElementById('edit-tag-input');
    _editTags.forEach(function(tag, idx) {
        var hue = N.Features.Memories.hashToHue(tag);
        var chip = document.createElement('span');
        chip.className = 'tag-chip-edit';
        chip.style.cssText = '--chip-hue:' + hue;
        safeSetHTML(chip, esc(tag) + ' <span class="tag-chip-remove" data-tidx="' + idx + '"><i data-lucide="x"></i></span>');
        wrap.insertBefore(chip, inp);
    });
    wrap.querySelectorAll('.tag-chip-remove').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var i = parseInt(btn.dataset.tidx, 10);
            _editTags.splice(i, 1);
            _renderEditTags();
        });
    });
}

function _addEditTag(val) {
    val = val.trim().toLowerCase();
    if (!val || _editTags.indexOf(val) !== -1) return;
    _editTags.push(val);
    _renderEditTags();
}

function openEditModal(mem) {
    document.getElementById('edit-modal-title').textContent = 'Edit Memory';
    document.getElementById('edit-content').value = mem.content || '';
    document.getElementById('edit-memory-key').value = mem.key || '';

    var imp = mem.importance != null ? mem.importance : 0.5;
    document.getElementById('edit-importance').value = imp;
    document.getElementById('edit-imp-val').textContent = imp.toFixed(2);

    document.getElementById('edit-emotion').value = mem.emotion || '';

    var emoInt = mem.emotion_intensity != null ? mem.emotion_intensity : 0;
    document.getElementById('edit-emo-intensity').value = emoInt;
    document.getElementById('edit-emo-val').textContent = emoInt.toFixed(2);

    _editTags = (mem.tags || []).slice();
    _renderEditTags();

    document.getElementById('mem-edit-overlay').classList.add('active');
}
/* N.Features.Memories.openEditModal registered below */

function openCreateModal() {
    document.getElementById('edit-modal-title').textContent = 'New Memory';
    document.getElementById('edit-content').value = '';
    document.getElementById('edit-memory-key').value = '';

    document.getElementById('edit-importance').value = 0.5;
    document.getElementById('edit-imp-val').textContent = '0.50';

    document.getElementById('edit-emotion').value = '';

    document.getElementById('edit-emo-intensity').value = 0;
    document.getElementById('edit-emo-val').textContent = '0.00';

    _editTags = [];
    _renderEditTags();

    document.getElementById('mem-edit-overlay').classList.add('active');
}

function closeEditModal() {
    document.getElementById('mem-edit-overlay').classList.remove('active');
}
/* N.Features.Memories.closeEditModal registered below */

/* ================================================================
   saveMemory
   ================================================================ */
async function saveMemory() {
    var contentVal = document.getElementById('edit-content').value.trim();
    if (!contentVal) { toast('Content is required', 'error'); return; }

    var key = document.getElementById('edit-memory-key').value;
    var imp = parseFloat(document.getElementById('edit-importance').value);
    var emoType = document.getElementById('edit-emotion').value;
    var emoInt = parseFloat(document.getElementById('edit-emo-intensity').value);

    var body = { content: contentVal, importance: imp, tags: _editTags.slice() };
    if (emoType) { body.emotion = emoType; body.emotion_intensity = emoInt; }

    try {
        if (key) {
            await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key), {
                method: 'PUT', body: JSON.stringify(body)
            });
            toast('Memory updated', 'success');
        } else {
            await api('/api/memories/' + encodeURIComponent(S.persona), {
                method: 'POST', body: JSON.stringify(body)
            });
            toast('Memory created', 'success');
        }
        closeEditModal();
        closeMemModal();
        N.Features.Memories.loadMemories();
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
}
/* N.Features.Memories.saveMemory registered below */

/* ================================================================
   deleteMemory
   ================================================================ */
async function deleteMemory(key) {
    N.Components.modal.showConfirm('この記憶を削除しますか？この操作は取り消せません。', async function() {
        try {
            await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key), {
                method: 'DELETE'
            });
            toast('Memory deleted', 'success');
            closeMemModal();
            N.Features.Memories.loadMemories();
        } catch (e) {
            toast('Delete failed: ' + e.message, 'error');
        }
    });
}
/* N.Features.Memories.deleteMemory registered below */

/* ================================================================
   batchDeleteMemories
   ================================================================ */
async function batchDeleteMemories() {
    var keys = Array.from(S.mem.selected);
    if (keys.length === 0) { toast('記憶が選択されていません', 'error'); return; }
    N.Components.modal.showConfirm(keys.length + '件の記憶を削除しますか？この操作は取り消せません。', async function() {
        var ok = 0, failures = [];
        for (var i = 0; i < keys.length; i++) {
            try {
                await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(keys[i]), {
                    method: 'DELETE'
                });
                ok++;
            } catch (e) {
                failures.push({ key: keys[i], reason: e.message });
                console.error('[batchDelete] failed:', keys[i], e);
            }
        }
        S.mem.selected.clear();
        if (failures.length > 0) {
            var detail = failures.slice(0, 3).map(function(f){ return f.key + ' (' + f.reason + ')'; }).join(', ');
            var summary = ok + ' deleted, ' + failures.length + ' failed';
            if (failures.length > 3) summary += ' (see console for full list)';
            toast(summary + ': ' + detail, 'error');
            console.error('[batchDelete] failure detail:', failures);
        } else {
            toast('Deleted ' + ok + ' memories', 'success');
        }
        N.Features.Memories.loadMemories();
    });
}

Object.assign(N.Features.Memories, {
    openMemModalByKey: openMemModalByKey,
    openMemModal: openMemModal,
    closeMemModal: closeMemModal,
    openEditModal: openEditModal,
    openCreateModal: openCreateModal,
    closeEditModal: closeEditModal,
    saveMemory: saveMemory,
    deleteMemory: deleteMemory,
    batchDeleteMemories: batchDeleteMemories,
    _editTags: _editTags,
    _renderEditTags: _renderEditTags,
    _addEditTag: _addEditTag,
});
})();
