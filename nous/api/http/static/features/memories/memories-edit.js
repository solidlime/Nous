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
    h += '<div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:4px">Memory Key</div>';
    h += '<div style="display:flex;align-items:center;gap:6px">';
    h += '<span style="font-family:monospace;font-size:0.85rem;color:var(--accent-purple)">' + esc(mem.key) + '</span>';
    h += '<button class="copy-btn" onclick="navigator.clipboard.writeText(\'' + esc(mem.key).replace(/'/g,'\\\'') + '\');window.Nous.Core.toast(\'Key copied!\',\'info\')" title="Copy key">\uD83D\uDCCB</button>';
    h += '</div></div>';
    h += '<button class="mem-modal-close" onclick="N.Features.Memories.closeMemModal()"><i data-lucide="x"></i></button>';
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
        h += '<span class="badge" style="background:' + emoColor + '22;color:' + emoColor + ';border:1px solid ' + emoColor + '44">' + esc(mem.emotion) + '</span>';
        if (mem.emotion_intensity != null) {
            h += ' <div class="modal-progress" style="display:inline-flex;width:120px;vertical-align:middle">';
            h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + (mem.emotion_intensity * 100) + '%;background:' + emoColor + '"></div></div>';
            h += '<span style="font-size:0.75rem;color:' + emoColor + '">' + mem.emotion_intensity.toFixed(2) + '</span></div>';
        }
        h += '</span></div>';
    }

    /* Importance */
    if (mem.importance != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Importance</span><span>';
        h += '<div class="modal-progress" style="display:inline-flex;width:160px">';
        h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + (mem.importance * 100) + '%;background:linear-gradient(90deg,var(--accent-purple),var(--accent-yellow))"></div></div>';
        h += '<span style="font-size:0.78rem;color:var(--accent-yellow);font-weight:600">' + mem.importance.toFixed(2) + '</span></div>';
        h += '</span></div>';
    }

    /* Strength */
    if (mem.strength != null) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Strength</span><span>';
        h += '<div class="modal-progress" style="display:inline-flex;width:160px">';
        h += '<div class="modal-progress-bar"><div class="modal-progress-fill" style="width:' + Math.min(mem.strength * 100, 100) + '%;background:linear-gradient(90deg,var(--accent-green),var(--accent-blue))"></div></div>';
        h += '<span style="font-size:0.78rem;color:var(--accent-green);font-weight:600">' + mem.strength.toFixed(3) + '</span></div>';
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
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Source</span><span style="color:var(--text-muted)">' + esc(mem.source_context) + '</span></div>';
    }

    /* Body State */
    if (mem.body_state) {
        var bodyKeys = Object.keys(N.Core.BODY_BAR_COLORS);
        var hasBody = bodyKeys.some(function(k){ return mem.body_state[k] != null; });
        if (hasBody) {
            h += '<div class=\"mem-modal-row\"><span class=\"mem-modal-key\">Body</span><span style=\"display:flex;flex-direction:column;gap:6px;flex:1\">';
            bodyKeys.forEach(function(k) {
                if (mem.body_state[k] != null) {
                    var val = mem.body_state[k];
                    var pct = Math.round(val * 100);
                    h += '<div style=\"display:flex;align-items:center;gap:8px\">';
                    h += '<span style=\"font-size:0.75rem;color:var(--text-muted);min-width:80px\">' + N.Core.BODY_LABELS[k] + '</span>';
                    h += '<div style=\"flex:1;height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden\">';
                    h += '<div style=\"height:100%;width:' + pct + '%;background:' + N.Core.BODY_BAR_COLORS[k] + ';border-radius:3px\"></div>';
                    h += '</div>';
                    h += '<span style=\"font-size:0.75rem;color:var(--text-muted);min-width:32px;text-align:right\">' + pct + '%</span>';
                    h += '</div>';
                }
            });
            h += '</span></div>';
        }
    }

    /* Emotion bar */
    if (mem.emotion) {
        h += '<div style=\"margin-bottom:16px\">' + N.Components.memoryCard.renderEmotionBars(mem.emotion, mem.emotion_intensity) + '</div>';
    }

    /* Created at */
    if (mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>\uD83D\uDCC5 ' + relativeTime(mem.created_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.created_at).toLocaleString() + ')</span></span></div>';
    }

    /* State snapped at (if different from created) */
    if (mem.state_snapped_at && mem.state_snapped_at !== mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">State</span><span><i data-lucide="camera-off"></i> ' + relativeTime(mem.state_snapped_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.state_snapped_at).toLocaleString() + ')</span></span></div>';
    }

    /* Updated at */
    if (mem.updated_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>\uD83D\uDCC5 ' + relativeTime(mem.updated_at) + ' <span style="color:var(--text-muted);font-size:0.75rem">(' + new Date(mem.updated_at).toLocaleString() + ')</span></span></div>';
    }

    /* Action buttons */
    h += '<div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">';
    h += '<button class="glass-btn glass-btn-danger" onclick="N.Features.Memories.deleteMemory(\'' + esc(mem.key).replace(/'/g,'\\\'') + '\')">\uD83D\uDDD1 Delete</button>';
    h += '<button class="glass-btn glass-btn-success" id="mem-modal-edit-btn">\u270F\uFE0F Edit</button>';
    h += '</div>';

    safeSetHTML(content, h);
    overlay.classList.add('show');
    document.removeEventListener('keydown', _memModalKeyHandler);
    document.addEventListener('keydown', _memModalKeyHandler);

    var editBtn = document.getElementById('mem-modal-edit-btn');
    if (editBtn) editBtn.onclick = function() { openEditModal(mem); };
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
        btn.onclick = function(e) {
            e.stopPropagation();
            var i = parseInt(btn.dataset.tidx);
            _editTags.splice(i, 1);
            _renderEditTags();
        };
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
