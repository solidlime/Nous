/* =================================================================
   MEMORIES EDIT — Modal display, edit/create forms, save/delete
   Namespace: N.Features.Memories.*
   Depends on: N.Core.* (api, esc, toast, relativeTime, showConfirm)
               N.Features.Memories.* (tagChipHtml, loadMemories)
               window.S, window.safeSetHTML, window.renderEmotionBars, window.lucide
   ================================================================= */
N.Features.Memories = N.Features.Memories || {};

;(function() {
var S = window.S;
var { esc, toast, api, relativeTime, showConfirm, safeSetHTML } = window.Nous.Core;

/* ================================================================
   openMemModalByKey — Fetch memory by key and open modal
   ================================================================ */
async function openMemModalByKey(key) {
    try {
        var data = await api('/api/memories/' + encodeURIComponent(S.persona) + '/' + encodeURIComponent(key));
        if (data.memory) {
            openMemModal(data.memory);
        } else {
            toast('Memory not found', 'error');
        }
    } catch (e) {
        toast('Failed to load memory: ' + e.message, 'error');
    }
}

/* ================================================================
   openMemModal — OVERRIDE base.py version
   ================================================================ */
function openMemModal(mem) {
    var overlay = document.getElementById('mem-modal-overlay');
    var content = document.getElementById('mem-modal-content');
    if (!overlay || !content) return;

    var tags = (mem.tags || []);
    var tagsHtml = tags.map(function(t){ return N.Features.Memories.tagChipHtml(t); }).join(' ');
    var emoColor = N.Core.EMOTION_COLORS[mem.emotion] || '#94a3b8';

    var h = '';
    h += '<div class="mem-modal-header">';
    h += '<div>';
    h += '<div class="mem-modal-kicker">Memory Key</div>';
    h += '<div class="mem-key-row">';
    h += '<span class="mem-key-mono">' + esc(mem.key) + '</span>';
    h += '<button type="button" class="copy-btn" data-mem-copy="1" title="Copy key">';
    h += '</div></div>';
    h += '<button type="button" class="mem-modal-close" data-mem-close="1"><i data-lucide="x"></i></button>';
    h += '</div>';

    /* Full content */
    h += '<div class="mem-modal-content">' + esc(mem.content) + '</div>';

    /* Tags */
    if (tagsHtml) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span>' + tagsHtml + '</span></div>';
    }

    /* Emotion */
    if (mem.emotion) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Emotion</span><span>';
        h += '<span class="badge mem-emo-badge" data-color-base="' + emoColor + '">' + esc(mem.emotion) + '</span>';
        if (mem.emotion_intensity != null) {
            h += ' <span class="modal-progress"><span class="modal-progress-bar"><span class="modal-progress-fill" data-fill="' + Math.round(mem.emotion_intensity * 100) + '" data-color="' + emoColor + '"></span></span><span class="mem-bar-pct">' + mem.emotion_intensity.toFixed(2) + '</span></span>';
        }
        h += '</span></div>';
    }

    /* Importance */
    if (mem.importance != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Importance</span><span>';
        h += '<span class="modal-progress"><span class="modal-progress-bar wide"><span class="modal-progress-fill" data-fill="' + Math.round(mem.importance * 100) + '" data-color="linear-gradient(90deg,var(--accent-purple),var(--accent-yellow))"></span></span><span class="mem-bar-pct ov-accent-yellow">' + mem.importance.toFixed(2) + '</span></span>';
        h += '</span></div>';
    }

    /* Strength */
    if (mem.strength != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Strength</span><span>';
        h += '<span class="modal-progress"><span class="modal-progress-bar wide"><span class="modal-progress-fill" data-fill="' + Math.round(Math.min(mem.strength * 100, 100)) + '" data-color="linear-gradient(90deg,var(--accent-green),var(--accent-blue))"></span></span><span class="mem-bar-pct ov-accent-green">' + mem.strength.toFixed(3) + '</span></span>';
        h += '</span></div>';
    }

    /* Score (search) */
    if (mem._score != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Search Score</span><span class="badge badge-green">' + mem._score.toFixed(3) + '</span></div>';
    }

    /* Privacy */
    if (mem.privacy_level) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Privacy</span><span>' + esc(mem.privacy_level) + '</span></div>';
    }

    /* Source context */
    if (mem.source_context) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Source</span><span class="ov-muted">' + esc(mem.source_context) + '</span></div>';
    }

    /* Body State (renderer + data-fill pass live in memory-card.js) */
    h += N.Components.memoryCard.renderBodyStateBars(mem.body_state);

    /* Emotion bar */
    if (mem.emotion) {
        h += N.Components.memoryCard.renderEmotionBars(mem.emotion, mem.emotion_intensity);
    }

    /* Created at */
    if (mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>\uD83D\uDCC5 ' + relativeTime(mem.created_at) + ' <span class="mem-time-note">(' + new Date(mem.created_at).toLocaleString() + ')</span></span></div>';
    }

    /* State snapped at (if different from created) */
    if (mem.state_snapped_at && mem.state_snapped_at !== mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">State</span><span><i data-lucide="camera-off"></i> ' + relativeTime(mem.state_snapped_at) + ' <span class="mem-time-note">(' + new Date(mem.state_snapped_at).toLocaleString() + ')</span></span></div>';
    }

    /* Updated at */
    if (mem.updated_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>\uD83D\uDCC5 ' + relativeTime(mem.updated_at) + ' <span class="mem-time-note">(' + new Date(mem.updated_at).toLocaleString() + ')</span></span></div>';
    }

    /* Action buttons */
    h += '<div class="ov-modal-actions">';
    h += '<button type="button" class="glass-btn glass-btn-danger" data-mem-del="1">Delete</button>';
    h += '<button class="glass-btn glass-btn-success" id="mem-modal-edit-btn">\u270F\uFE0F Edit</button>';
    h += '</div>';

    safeSetHTML(content, h);
    overlay.classList.add('show');
    document.removeEventListener('keydown', _memModalKeyHandler);
    document.addEventListener('keydown', _memModalKeyHandler);

    var editBtn = document.getElementById('mem-modal-edit-btn');
    if (editBtn) editBtn.addEventListener('click', function() { openEditModal(mem); });
    /* CSP-safe bindings (no inline onclick): copy key / close / delete */
    var copyBtn = content.querySelector('[data-mem-copy]');
    if (copyBtn) copyBtn.addEventListener('click', function() {
        var done = function() { toast('Key copied!', 'info'); };
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            navigator.clipboard.writeText(mem.key).then(done, done);
        } else { done(); }
    });
    var closeBtn = content.querySelector('[data-mem-close]');
    if (closeBtn) closeBtn.addEventListener('click', function() { closeMemModal(); });
    var delBtn = content.querySelector('[data-mem-del]');
    if (delBtn) delBtn.addEventListener('click', function() { deleteMemory(mem.key); });
}
/* N.Features.Memories.openMemModal registered below */

/* ================================================================
   closeMemModal — companion to openMemModal (rich version)
   ================================================================ */
function closeMemModal() {
    var overlay = document.getElementById('mem-modal-overlay');
    if (!overlay || !overlay.classList.contains('show')) return;
    overlay.classList.remove('show');
    document.removeEventListener('keydown', _memModalKeyHandler);
}
/* N.Features.Memories.closeMemModal registered below */

function _memModalKeyHandler(e) {
    if (e.key === 'Escape') closeMemModal();
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
    _memModalKeyHandler: _memModalKeyHandler,
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
