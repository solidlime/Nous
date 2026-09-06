/* =================================================================
   MEM MODAL COMPONENT — N.Components.memModal
   THE memory detail view. All tabs (Memories / Timeline / Graph /
   Chat wiring) open memory details through this modal — never build
   a bespoke detail panel per tab.

   Entry point:  N.Components.memModal.open(key)   (fetch by key)
   Raw variant:  N.Components.memModal.openMemory(mem)
   Companion:    N.Components.memModal.close()

   DOM: #mem-modal-overlay is server-generated (sections/base.py) and
   lives OUTSIDE tab panels so any tab can open it. Backdrop click is
   bound in base.js; Escape is bound here.
   ================================================================= */
;(function(N) {
"use strict";

var C = N.Core;
var esc = C.esc, toast = C.toast, api = C.api, relativeTime = C.relativeTime, fmtDateTime = C.fmtDateTime;
var safeSetHTML = C.safeSetHTML;

/* ── open(key) — Fetch memory by key and open the modal ── */
async function openMemModalByKey(key) {
    try {
        /* window.S is read at call time — mem-modal.js loads before
           base.js assigns window.S, so a load-time capture would be
           stale. */
        var persona = window.S && window.S.persona;
        var data = await api('/api/memories/' + encodeURIComponent(persona) + '/' + encodeURIComponent(key));
        if (data.memory) {
            openMemModal(data.memory);
        } else {
            toast('Memory not found', 'error');
        }
    } catch (e) {
        toast('Failed to load memory: ' + e.message, 'error');
    }
}

/* ── openMemory(mem) — render a memory object into the modal ── */
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
    h += '<div class="mem-modal-body">' + esc(mem.content) + '</div>';

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
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>\uD83D\uDCC5 ' + relativeTime(mem.created_at) + ' <span class="mem-time-note">(' + fmtDateTime(mem.created_at) + ')</span></span></div>';
    }

    /* State snapped at (if different from created) */
    if (mem.state_snapped_at && mem.state_snapped_at !== mem.created_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">State</span><span><i data-lucide="camera-off"></i> ' + relativeTime(mem.state_snapped_at) + ' <span class="mem-time-note">(' + fmtDateTime(mem.state_snapped_at) + ')</span></span></div>';
    }

    /* Updated at */
    if (mem.updated_at) {
        h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>\uD83D\uDCC5 ' + relativeTime(mem.updated_at) + ' <span class="mem-time-note">(' + fmtDateTime(mem.updated_at) + ')</span></span></div>';
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
    if (editBtn) editBtn.addEventListener('click', function() { N.Features.Memories.openEditModal(mem); });
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
    if (delBtn) delBtn.addEventListener('click', function() { N.Features.Memories.deleteMemory(mem.key); });
}

/* ── close() — companion to openMemory ── */
function closeMemModal() {
    var overlay = document.getElementById('mem-modal-overlay');
    if (!overlay || !overlay.classList.contains('show')) return;
    overlay.classList.remove('show');
    document.removeEventListener('keydown', _memModalKeyHandler);
}

function _memModalKeyHandler(e) {
    if (e.key === 'Escape') closeMemModal();
}

/* ── Export ── */
N.Components.memModal = {
    open: openMemModalByKey,
    openMemory: openMemModal,
    close: closeMemModal,
};

})(window.Nous);
