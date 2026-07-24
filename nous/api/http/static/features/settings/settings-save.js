/* =================================================================
   SETTINGS SAVE — Auto-save, reset, status polling, profiles
   Namespace: N.Features.Settings.*
   Depends on: N.Core.* (api, safeSetHTML, esc, toast)
               N.Features.Settings.validateField (settings-validation.js)
               window.S, window.lucide
   ================================================================= */
N.Features.Settings = N.Features.Settings || {};

;(function() {
var S = window.S;
var { esc, toast, api } = window.Nous.Core;

const BUILTIN_PROFILES = {
    'Development': {
        server: { host: '0.0.0.0', port: 26262 },
        embedding: { model: 'onnx-community/ruri-v3-30m-ONNX', device: 'cpu' },
        reranker: { model: 'hotchpotch/japanese-reranker-xsmall-v2', enabled: true },
        general: { log_level: 'DEBUG', contradiction_threshold: 0.85, duplicate_threshold: 0.90 }
    },
    'Production': {
        embedding: { model: 'onnx-community/ruri-v3-30m-ONNX', device: 'auto' },
        reranker: { model: 'hotchpotch/japanese-reranker-xsmall-v2', enabled: true },
        general: { log_level: 'WARNING', contradiction_threshold: 0.85, duplicate_threshold: 0.90 }
    }
};

const RELOAD_CATEGORIES = new Set(['embedding', 'reranker', 'qdrant']);

/* ═══════════════════════════════════════════════════════════════════
   AUTO-SAVE DEBOUNCE & HELPERS
   ═══════════════════════════════════════════════════════════════════ */

const _autoSaveTimers = {};

function debounceAutoSave(cat, key, inputId, value) {
    var timerKey = cat + '.' + key;
    if (_autoSaveTimers[timerKey]) clearTimeout(_autoSaveTimers[timerKey]);
    _autoSaveTimers[timerKey] = setTimeout(function() {
        doAutoSave(cat, key, inputId, value);
    }, 300);
}

async function doAutoSave(cat, key, inputId, value) {
    var statusEl = document.getElementById('status-' + inputId);
    var input = document.getElementById(inputId);
    if (!statusEl) return;

    /* Show saving state */
    statusEl.className = 'setting-status status-saving visible';
    safeSetHTML(statusEl, '<span class="setting-spinner"></span> Saving...');

    /* Clear previous error */
    var row = input ? input.closest('.setting-row') : null;
    var errEl = row ? row.querySelector('.setting-inline-error') : null;
    if (errEl) { errEl.textContent = ''; errEl.className = 'setting-inline-error'; }

    try {
        await api('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ category: cat, key: key, value: value })
        });

        /* Show saved state */
        statusEl.className = 'setting-status status-saved visible';
        safeSetHTML(statusEl, '✓ Saved');

        /* Update source badge to "override" */
        if (row) {
            var srcEl = row.querySelector('.setting-source');
            if (srcEl) {
                srcEl.className = 'setting-source source-override';
                srcEl.title = 'Set via WebUI override';
                safeSetHTML(srcEl, '<i data-lucide="edit-3"></i> override');
            }
            /* Show reset button and diff dot */
            var resetBtn = row.querySelector('.setting-reset-btn');
            if (resetBtn) resetBtn.style.display = '';
            var diffDot = row.querySelector('.setting-diff-dot');
            if (diffDot) diffDot.style.display = '';
        }

        /* Start polling for reload categories */
        if (RELOAD_CATEGORIES.has(cat)) {
            statusEl.className = 'setting-status status-reloading visible';
            safeSetHTML(statusEl, '<span class="setting-spinner reloading"></span> Reloading...');
            startStatusPoll();
        }

        /* Auto-fade saved indicator after 2s (only if not reloading) */
        if (!RELOAD_CATEGORIES.has(cat)) {
            setTimeout(function() {
                if (statusEl.className.indexOf('status-saved') !== -1) {
                    statusEl.classList.remove('visible');
                }
            }, 2000);
        }

        /* Update internal data */
        if (S.settingsData && S.settingsData[cat] && S.settingsData[cat][key]) {
            S.settingsData[cat][key].value = value;
            S.settingsData[cat][key].source = 'override';
        }
    } catch (e) {
        /* Show error state */
        var errMsg = e.message || 'Save failed';
        statusEl.className = 'setting-status status-error visible';
        safeSetHTML(statusEl, '✕ Error');
        if (errEl) {
            errEl.textContent = errMsg;
            errEl.className = 'setting-inline-error visible';
        }
        /* Auto-fade error after 3s */
        setTimeout(function() {
            statusEl.classList.remove('visible');
            if (errEl) errEl.classList.remove('visible');
        }, 3000);
    }
}

/* ═══════════════════════════════════════════════════════════════════
   RESET FUNCTIONS
   ═══════════════════════════════════════════════════════════════════ */

async function resetField(cat, key, defaultVal) {
    var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
    var isHot = meta && meta.hot_reload !== false;
    try {
        await api('/api/settings', { method: 'PUT', body: JSON.stringify({ category: cat, key: key, value: defaultVal }) });
        toast('<i data-lucide="check-circle"></i> Reset ' + cat + '.' + key + ' to default', 'success');
        if (isHot) {
            /* Auto-save field: update input and status inline */
            var inputId = 'setting-' + cat + '-' + key;
            var input = document.getElementById(inputId);
            if (input) {
                if (input.tagName === 'SELECT') {
                    input.value = String(defaultVal);
                } else {
                    input.value = defaultVal != null ? String(defaultVal) : '';
                }
            }
            /* Update status indicator */
            var statusEl = document.getElementById('status-' + inputId);
            if (statusEl) {
                statusEl.className = 'setting-status status-saved visible';
                safeSetHTML(statusEl, '✓ Saved');
                setTimeout(function() { statusEl.classList.remove('visible'); }, 2000);
            }
            /* Update internal data */
            if (S.settingsData && S.settingsData[cat] && S.settingsData[cat][key]) {
                S.settingsData[cat][key].value = defaultVal;
                S.settingsData[cat][key].source = 'default';
            }
            /* Hide reset button and diff dot, update source badge */
            var row = input ? input.closest('.setting-row') : null;
            if (row) {
                var resetBtn = row.querySelector('.setting-reset-btn');
                if (resetBtn) resetBtn.style.display = 'none';
                var diffDot = row.querySelector('.setting-diff-dot');
                if (diffDot) diffDot.style.display = 'none';
                var srcEl = row.querySelector('.setting-source');
                if (srcEl) {
                    srcEl.className = 'setting-source source-default';
                    srcEl.title = 'Using default value';
                    safeSetHTML(srcEl, '<i data-lucide="clipboard-list"></i> default');
                }
            }
            /* Start polling for reload categories */
            if (RELOAD_CATEGORIES.has(cat)) startStatusPoll();
        } else {
            /* Restart-required field: reload to show updated source badge */
            setTimeout(function() { window.loadSettings(); }, 800);
        }
    } catch (e) {
        toast('<i data-lucide="x-circle"></i> Reset failed: ' + e.message, 'error');
    }
}

async function resetCategory(cat) {
    if (!confirm('Reset all ' + cat + ' settings to defaults?')) return;
    var settings = S.settingsData;
    if (!settings || !settings[cat]) return;
    var isHotCat = !RELOAD_CATEGORIES.has(cat) && cat !== 'server' && cat !== 'general';
    try {
        var count = 0;
        for (const [key, meta] of Object.entries(settings[cat])) {
            if (meta && meta.source === 'override' && meta.default_value != null) {
                await api('/api/settings', { method: 'PUT', body: JSON.stringify({ category: cat, key: key, value: meta.default_value }) });
                count++;
            }
        }
        toast('<i data-lucide="check-circle"></i> Category ' + cat + ' reset (' + count + ' settings)', 'success');
        if (RELOAD_CATEGORIES.has(cat)) {
            startStatusPoll();
        } else {
            setTimeout(function() { window.loadSettings(); }, 800);
        }
    } catch (e) {
        toast('<i data-lucide="x-circle"></i> Reset failed: ' + e.message, 'error');
    }
}

/* ═══════════════════════════════════════════════════════════════════
   STATUS POLLING
   ═══════════════════════════════════════════════════════════════════ */

function startStatusPoll() {
    if (S.statusPoll) clearInterval(S.statusPoll);
    S.statusPoll = setInterval(async function() {
        try {
            var status = await api('/api/settings/status');
            var rs = status.reload_status || {};
            var allDone = Object.values(rs).every(function(s) {
                return !s.status || s.status === 'idle' || s.status === 'ready' || s.status === 'success' || s.status === 'error';
            });
            if (allDone) {
                clearInterval(S.statusPoll);
                S.statusPoll = null;
                /* Update per-field status indicators to show completion */
                RELOAD_CATEGORIES.forEach(function(cat) {
                    var s = rs[cat];
                    if (s && (s.status === 'ready' || s.status === 'success')) {
                        document.querySelectorAll('[data-category="' + cat + '"] .setting-status.status-reloading').forEach(function(el) {
                            el.className = 'setting-status status-saved visible';
                            safeSetHTML(el, '✓ Ready');
                            setTimeout(function() { el.classList.remove('visible'); }, 2000);
                        });
                    } else if (s && s.status === 'error') {
                        document.querySelectorAll('[data-category="' + cat + '"] .setting-status.status-reloading').forEach(function(el) {
                            el.className = 'setting-status status-error visible';
                            safeSetHTML(el, '✕ Error');
                            setTimeout(function() { el.classList.remove('visible'); }, 3000);
                        });
                    }
                });
                /* Update category-level status banners */
                updateCategoryStatusBanners(rs);
            } else {
                /* Update category-level status banners for loading state */
                updateCategoryStatusBanners(rs);
            }
        } catch(e) { /* ignore poll errors */ }
    }, 2000);
}

function updateCategoryStatusBanners(rs) {
    RELOAD_CATEGORIES.forEach(function(cat) {
        var s = rs[cat];
        var statusHtml = '';
        if (s && s.status === 'loading') {
            statusHtml = '<div style="margin-top:8px"><div style="font-size:0.78rem;color:var(--accent-yellow);margin-bottom:4px"><i data-lucide="clock"></i> Reloading ' + esc(cat) + ' model...</div><div class="progress-wrap"><div class="progress-bar progress-indeterminate"></div></div></div>';
        } else if (s && (s.status === 'ready' || s.status === 'success')) {
            statusHtml = '<div style="margin-top:8px;font-size:0.78rem;color:var(--accent-green)"><i data-lucide="check-circle"></i> ' + esc(cat) + ' ready</div>';
        } else if (s && s.status === 'error') {
            statusHtml = '<div style="margin-top:8px;font-size:0.78rem;color:var(--accent-red)"><i data-lucide="x-circle"></i> ' + esc(cat) + ' error: ' + esc(s.error || 'Unknown') + '</div>';
        }
        var card = document.querySelector('[data-category="' + cat + '"]');
        if (card) {
            var existing = card.querySelector('.cat-reload-status');
            if (statusHtml) {
                if (existing) {
                    safeSetHTML(existing, statusHtml);
                } else {
                    var div = document.createElement('div');
                    div.className = 'cat-reload-status';
                    safeSetHTML(div, statusHtml);
                    var body = card.querySelector('.cat-body');
                    if (body) body.insertAdjacentElement('beforebegin', div);
                }
                if (typeof lucide !== 'undefined') lucide.createIcons();
            } else if (existing) {
                existing.remove();
            }
        }
    });
}

/* ═══════════════════════════════════════════════════════════════════
   PROFILES
   ═══════════════════════════════════════════════════════════════════ */

function saveSettingsProfile() {
    var name = prompt('Enter profile name:');
    if (!name || !name.trim()) return;
    var settings = S.settingsData;
    if (!settings) { toast('No settings loaded', 'error'); return; }
    var profile = {};
    Object.entries(settings).forEach(function(entry) {
        var cat = entry[0], fields = entry[1];
        if (typeof fields !== 'object' || fields === null) return;
        profile[cat] = {};
        Object.entries(fields).forEach(function(e2) {
            var key = e2[0], meta = e2[1];
            if (meta && meta.value != null && String(meta.value) !== '***') profile[cat][key] = meta.value;
        });
    });
    localStorage.setItem('nous_profile_' + name.trim(), JSON.stringify(profile));
    toast('<i data-lucide="save"></i> Profile "' + esc(name.trim()) + '" saved', 'success');
    renderSettingsProfiles();
}

async function loadSettingsProfile(name, profile) {
    if (!confirm('Load profile "' + esc(name) + '"? This will apply all settings from the profile.')) return;
    try {
        var count = 0;
        for (const [cat, fields] of Object.entries(profile)) {
            for (const [key, value] of Object.entries(fields)) {
                await api('/api/settings', { method: 'PUT', body: JSON.stringify({ category: cat, key: key, value: value }) });
                count++;
            }
        }
        toast('<i data-lucide="check-circle"></i> Loaded profile "' + esc(name) + '" (' + count + ' settings)', 'success');
        setTimeout(function() { window.loadSettings(); }, 1000);
    } catch (e) {
        toast('<i data-lucide="x-circle"></i> Failed to load profile: ' + e.message, 'error');
    }
}

function deleteSettingsProfile(name) {
    if (!confirm('Delete profile "' + esc(name) + '"?')) return;
    localStorage.removeItem('nous_profile_' + name);
    toast('Profile "' + esc(name) + '" deleted', 'info');
    renderSettingsProfiles();
}

function renderSettingsProfiles() {
    var container = document.getElementById('profiles-list');
    if (!container) return;
    var html = '';
    /* Built-in profiles */
    Object.keys(BUILTIN_PROFILES).forEach(function(name) {
        html += '<button data-profile-action="load-builtin" data-profile-name="' + esc(name) + '" class="glass-btn profile-chip" style="padding:5px 14px;font-size:0.78rem;background:linear-gradient(135deg,rgba(var(--accent-blue-rgb),0.15),rgba(var(--accent-pink-rgb),0.15));border-color:rgba(var(--accent-blue-rgb),0.3)">';
        html += '<i data-lucide="package"></i> ' + esc(name);
        html += '</button>';
    });
    /* User profiles from localStorage */
    var profileKeys = [];
    for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.startsWith('nous_profile_')) profileKeys.push(k);
    }
    profileKeys.forEach(function(k) {
        var pName = k.replace('nous_profile_', '');
        html += '<div style="display:inline-flex;align-items:center;gap:0">';
        html += '<button data-profile-action="load-user" data-profile-name="' + esc(pName) + '" class="glass-btn profile-chip" style="padding:5px 14px;font-size:0.78rem;border-top-right-radius:0;border-bottom-right-radius:0">';
        html += '<i data-lucide="user"></i> ' + esc(pName);
        html += '</button>';
        html += '<button data-profile-action="delete" data-profile-name="' + esc(pName) + '" class="glass-btn glass-btn-danger" style="padding:5px 8px;font-size:0.72rem;border-top-left-radius:0;border-bottom-left-radius:0;border-left:none" title="Delete profile"><i data-lucide="x"></i></button>';
        html += '</div>';
    });
    if (!html) html = '<span style="font-size:0.8rem;color:var(--text-muted)">No profiles yet</span>';
    safeSetHTML(container, html);
}

Object.assign(N.Features.Settings, {
    BUILTIN_PROFILES: BUILTIN_PROFILES,
    RELOAD_CATEGORIES: RELOAD_CATEGORIES,
    debounceAutoSave: debounceAutoSave,
    doAutoSave: doAutoSave,
    resetField: resetField,
    resetCategory: resetCategory,
    startStatusPoll: startStatusPoll,
    updateCategoryStatusBanners: updateCategoryStatusBanners,
    saveSettingsProfile: saveSettingsProfile,
    loadSettingsProfile: loadSettingsProfile,
    deleteSettingsProfile: deleteSettingsProfile,
    renderSettingsProfiles: renderSettingsProfiles,
});
})();
