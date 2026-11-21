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

var EDIT_MODAL_HTML = '' +
    '<div id="mem-edit-overlay" class="mem-edit-overlay" data-action="mem-edit-backdrop">' +
      '<div class="mem-edit-modal">' +
        '<div class="mem-modal-header">' +
          '<h3 id="edit-modal-title">New Memory</h3>' +
          '<button type="button" class="mem-modal-close" data-action="mem-edit-close" aria-label="閉じる">&#10005;</button>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label" for="edit-content">Content *</label>' +
          '<textarea id="edit-content" class="form-textarea" placeholder="Memory content..."></textarea>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label" for="edit-tag-input">Tags</label>' +
          '<div class="tags-input-wrap" id="edit-tags-wrap">' +
            '<input type="text" class="tag-text-input" id="edit-tag-input" placeholder="Type tag + Enter" autocomplete="off">' +
          '</div>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label" for="edit-importance">Importance</label>' +
          '<div class="range-row">' +
            '<span class="range-value" id="edit-imp-val">0.50</span>' +
            '<input type="range" class="glass-range" id="edit-importance" min="0" max="1" step="0.05" value="0.5">' +
          '</div>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label" for="edit-emotion">Emotion Type</label>' +
          '<select id="edit-emotion" class="glass-input">' +
            '<option value="">None</option>' +
            '<option value="joy">Joy</option>' +
            '<option value="sadness">Sadness</option>' +
            '<option value="anger">Anger</option>' +
            '<option value="fear">Fear</option>' +
            '<option value="surprise">Surprise</option>' +
            '<option value="disgust">Disgust</option>' +
            '<option value="love">Love</option>' +
            '<option value="neutral">Neutral</option>' +
            '<option value="anticipation">Anticipation</option>' +
            '<option value="trust">Trust</option>' +
            '<option value="anxiety">Anxiety</option>' +
            '<option value="excitement">Excitement</option>' +
            '<option value="frustration">Frustration</option>' +
            '<option value="nostalgia">Nostalgia</option>' +
            '<option value="pride">Pride</option>' +
            '<option value="shame">Shame</option>' +
            '<option value="guilt">Guilt</option>' +
            '<option value="loneliness">Loneliness</option>' +
            '<option value="contentment">Contentment</option>' +
            '<option value="curiosity">Curiosity</option>' +
            '<option value="awe">Awe</option>' +
            '<option value="relief">Relief</option>' +
          '</select>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label" for="edit-emo-intensity">Emotion Intensity</label>' +
          '<div class="range-row">' +
            '<span class="range-value" id="edit-emo-val">0.00</span>' +
            '<input type="range" class="glass-range" id="edit-emo-intensity" min="0" max="1" step="0.01" value="0">' +
          '</div>' +
        '</div>' +
        '<input type="hidden" id="edit-memory-key" value="">' +
        '<div class="persona-modal-actions">' +
          '<button type="button" class="glass-btn" data-action="mem-edit-close">Cancel</button>' +
          '<button type="button" class="glass-btn" data-action="mem-edit-save">Save</button>' +
        '</div>' +
      '</div>' +
    '</div>';

/* v4: タブ遅延化でシェルにモーダルを載せていない（render_lazy_tab は
   #memories-content しか吐かない）ため、初回 open 時に自前で建てる。id と
   data-action は sections/memories.py の SSR 版と同一（core/delegation.js と
   bindMemoryEvents が直参照している）。style 属性は safeSetHTML の
   FORBID_ATTR で落ちるので、寸法は attribute ではなく JS で当てる。 */
function _ensureEditModal() {
    if (document.getElementById('mem-edit-overlay')) return null;
    var host = document.createElement('div');
    safeSetHTML(host, EDIT_MODAL_HTML);
    var overlay = host.firstElementChild;
    if (!overlay) return null;
    document.body.appendChild(overlay);

    // 44px touch target（styles/* は A レーンなので CSS ではなくここで当てる）
    ['edit-tag-input', 'edit-emotion', 'edit-importance'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.style.minHeight = '44px';
    });
    overlay.querySelectorAll('.glass-btn, .mem-modal-close').forEach(function(b) {
        b.style.minHeight = '44px';
        b.style.minWidth = '44px';
    });

    // 生成直後にしか効かないバインディング。bindMemoryEvents は一覧 render 後に
    // 走るため、遅延生成されたモーダルには初回到達しない（同一内容で冪等）。
    var impEl = document.getElementById('edit-importance');
    if (impEl) impEl.oninput = function() {
        var v = document.getElementById('edit-imp-val');
        if (v) v.textContent = parseFloat(impEl.value).toFixed(2);
    };
    var emoEl = document.getElementById('edit-emo-intensity');
    if (emoEl) emoEl.oninput = function() {
        var v = document.getElementById('edit-emo-val');
        if (v) v.textContent = parseFloat(emoEl.value).toFixed(2);
    };
    var tagInput = document.getElementById('edit-tag-input');
    if (tagInput) tagInput.onkeydown = function(e) {
        // Enter はタグ確定のみ。送信はしない（登録UI 仕様）。
        if (e.key !== 'Enter') return;
        e.preventDefault();
        var val = tagInput.value.trim();
        if (!val) return;
        _addEditTag(val);
        tagInput.value = '';
    };
    return overlay;
}

function openEditModal(mem) {
    _ensureEditModal();
    document.getElementById('edit-modal-title').textContent = 'Edit Memory';
    document.getElementById('edit-content').value = mem.content || '';
    document.getElementById('edit-memory-key').value = mem.key || '';

    var imp = mem.importance != null ? mem.importance : 0.5;
    var impEl = document.getElementById('edit-importance');
    impEl.step = '0.01';  // 既存 importance を step=0.05 に丸めない（登録UIのみ0.05）
    impEl.value = imp;
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
    _ensureEditModal();
    document.getElementById('edit-modal-title').textContent = 'New Memory';
    document.getElementById('edit-content').value = '';
    document.getElementById('edit-memory-key').value = '';

    var impEl = document.getElementById('edit-importance');
    impEl.step = '0.05';
    impEl.value = 0.5;
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
var _saving = false;
async function saveMemory() {
    if (_saving) return;  // 連打ガード（二重 POST 防止）
    var contentVal = document.getElementById('edit-content').value.trim();
    if (!contentVal) { toast('Content is required', 'error'); return; }

    var key = document.getElementById('edit-memory-key').value;
    var imp = parseFloat(document.getElementById('edit-importance').value);
    var emoType = document.getElementById('edit-emotion').value;
    var emoInt = parseFloat(document.getElementById('edit-emo-intensity').value);

    var body = { content: contentVal, importance: imp, tags: _editTags.slice() };
    if (emoType) { body.emotion = emoType; body.emotion_intensity = emoInt; }

    _saving = true;
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
    } finally {
        _saving = false;
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
