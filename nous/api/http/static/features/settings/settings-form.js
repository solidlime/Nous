/* =================================================================
   SETTINGS FORM — Rendering + event binding
   Namespace: N.Features.Settings.*
   Depends on: N.Core.* (api, esc, toast, safeSetHTML, lucide)
               N.Features.Settings.* (validateField, debounceAutoSave, startStatusPoll,
                 resetField, resetCategory, saveSettingsProfile, loadSettingsProfile,
                 deleteSettingsProfile, renderSettingsProfiles, BUILTIN_PROFILES,
                 CATEGORY_ICONS, CATEGORY_DESCRIPTIONS, CATEGORY_ORDER,
                 sourceIcon, filterSettings, toggleCategory)
                 window.S, N.Core.animateCards, window.lucide
   Constants / icons / search / toggle → settings-ui.js
   ================================================================= */
N.Features.Settings = N.Features.Settings || {};

;(function() {
var S = window.S;
var { esc, toast, api, safeSetHTML } = window.Nous.Core;

/* ═══════════════════════════════════════════════════════════════════
   RENDER SETTINGS
   ═══════════════════════════════════════════════════════════════════ */

function renderSettings(el, settings, status) {
    var reloadStatus = (status && status.reload_status) || {};
    var html = '';

    /* ── Profiles section ── */
    html += '<div class="glass p-4 mb-6">';
    html += '<div class="settings-card-header">';
    html += '<h3 class="settings-card-title"><i data-lucide="clipboard-list"></i> Settings Profiles</h3>';
    html += '<button id="save-profile-btn" class="glass-btn"><i data-lucide="save"></i> Save Current as Profile</button>';
    html += '</div>';
    html += '<div id="profiles-list" class="profiles-list"></div>';
    html += '</div>';

    /* ── Search bar (classes in components.css — no inline style: stripped by sanitizer) ── */
    html += '<div class="glass p-4 mb-6 settings-search-card">';
    html += '<div class="settings-search-wrap">';
    html += '<span class="settings-search-icon"><i data-lucide="search"></i></span>';
    html += '<input id="settings-search" type="text" class="glass-input" placeholder="Search settings...">';
    html += '<button type="button" id="settings-search-clear"><i data-lucide="x"></i></button>';
    html += '</div>';
    html += '</div>';

    /* ── Category cards ── */
    var sortedCats = N.Features.Settings.CATEGORY_ORDER.filter(function(c) { return settings[c]; });
    /* Append any categories not in CATEGORY_ORDER (future-proofing) */
    Object.keys(settings).forEach(function(c) {
        if (c !== 'reload_status' && sortedCats.indexOf(c) === -1) sortedCats.push(c);
    });

    sortedCats.forEach(function(cat) {
        var fields = settings[cat];
        if (typeof fields !== 'object' || fields === null) return;
        var hasFields = Object.values(fields).some(function(f) { return typeof f === 'object' && f !== null; });
        if (!hasFields) return;

        var icon = N.Features.Settings.CATEGORY_ICONS[cat] || '<i data-lucide="settings"></i>';
        var catLabel = cat.replace(/_/g, ' ').replace(/\b\w/g, function(l) { return l.toUpperCase(); });
        var catDesc = N.Features.Settings.CATEGORY_DESCRIPTIONS[cat] || '';

        /* Diff detection for category */
        var hasDiffs = false;
        var catSearchText = cat + ' ' + catLabel;
        Object.entries(fields).forEach(function(entry) {
            var key = entry[0], meta = entry[1];
            if (typeof meta !== 'object' || meta === null) return;
            if (meta.value != null && meta.default_value != null && String(meta.value) !== '***') {
                if (String(meta.value) !== String(meta.default_value)) { hasDiffs = true; }
            }
        });

        /* Reload status */
        var catStatus = reloadStatus[cat];
        var statusHtml = '';
        if (catStatus && catStatus.status && catStatus.status !== 'idle') {
            var st = catStatus.status;
            if (st === 'loading' || st === 'reloading') {
                statusHtml = '<div class="cat-status"><div class="cat-status-loading"><i data-lucide="clock"></i> ' + esc(catStatus.message || '読み込み中…') + '</div><div class="progress-wrap"><div class="progress-bar progress-indeterminate"></div></div></div>';
            } else if (st === 'ready' || st === 'success') {
                statusHtml = '<div class="cat-status cat-status-ready"><i data-lucide="check-circle"></i> ' + esc(catStatus.message || '準備完了') + '</div>';
            } else if (st === 'error') {
                statusHtml = '<div class="cat-status cat-status-error"><i data-lucide="x-circle"></i> ' + esc(catStatus.message || 'エラー') + '</div>';
            }
        }

        /* Card wrapper */
        html += '<div class="glass p-6 mb-6 setting-category-card" data-category="' + esc(cat) + '" data-searchtext="' + esc(catSearchText) + '">';
        html += '<div class="settings-card-header">';
        html += '<div class="settings-card-header-group">';
        html += '<button class="cat-toggle-btn" id="cat-toggle-' + cat + '" data-toggle-cat="' + cat + '" title="Toggle section">▼</button>';
        html += '<span class="card-title">' + icon + ' ' + esc(catLabel) + '</span>';
        html += '</div>';
        html += '<div class="settings-card-header-group">';
        if (hasDiffs) {
            html += '<button class="cat-reset-btn" data-reset-cat="' + cat + '">↩ Reset Category</button>';
        }
        html += '</div>';
        html += '</div>';

        /* Category description */
        if (catDesc) {
            html += '<div class="cat-desc">' + esc(catDesc) + '</div>';
        }

        html += statusHtml;
        html += '<div id="cat-body-' + cat + '" class="cat-body">';

        /* ── Fields (Q9: general.api_key renders first — display order only) ── */
        var fieldEntries = Object.entries(fields);
        if (cat === 'general') {
            fieldEntries.sort(function(a, b) {
                if (a[0] === 'api_key') return -1;
                if (b[0] === 'api_key') return 1;
                return 0;
            });
        }
        fieldEntries.forEach(function(entry) {
            var key = entry[0], meta = entry[1];
            if (typeof meta !== 'object' || meta === null) return;
            var val = meta.value != null ? meta.value : '';
            var defaultVal = meta.default_value;
            var src = meta.source || 'default';
            var hot = meta.hot_reload !== false;
            var isMasked = meta.masked === true || String(val) === '***';
            var inputId = 'setting-' + cat + '-' + key;
            var isBool = val === true || val === false;
            var desc = meta.description || '';
            var isDiff = !isMasked && defaultVal != null && String(val) !== String(defaultVal);
            var reloadHint = hot
                ? '<i data-lucide="refresh-cw" class="lucide-sm"></i> Hot-reload'
                : '<i data-lucide="lock" class="lucide-sm"></i> Restart required';
            var tooltipText = reloadHint + (meta.reload_time ? ' (' + meta.reload_time + ')' : '');
            var searchText = key.replace(/_/g, ' ') + ' ' + desc + ' ' + cat;

            html += '<div class="setting-row' + (isDiff ? ' is-diff' : '') + '" data-setting-key="' + cat + '.' + key + '" data-category="' + cat + '" data-searchtext="' + esc(searchText) + '">';

            /* Label column with diff dot */
            html += '<div class="setting-label-col">';
            html += '<span class="setting-diff-dot"></span>';
            html += '<label class="setting-label" for="' + inputId + '" title="' + esc(tooltipText) + '">' + esc(key.replace(/_/g, ' ')) + '</label>';
            if (desc) html += '<span class="setting-desc">' + esc(desc) + '</span>';
            html += '</div>';

            /* Source icon */
            html += N.Features.Settings.sourceIcon(src);

            /* Input element */
            var autosaveAttr = hot ? ' data-autosave="true"' : '';
            if (isMasked) {
                /* ── Password / masked field with toggle ── */
                html += '<div class="setting-input-col">';
                html += '<input id="' + inputId + '" type="password" class="glass-input" value="" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '" data-masked="true"' + autosaveAttr + ' placeholder="' + (isMasked ? 'stored: 16+ chars to change, clear to restore open access' : 'Enter value...') + '">';
                html += '<button class="pw-toggle-btn" data-input="' + inputId + '" title="Show/hide"><i data-lucide="eye"></i></button>';
                html += '</div>';
            } else if (key === 'log_level') {
                html += '<select id="' + inputId + '" class="glass-input" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                ['DEBUG','INFO','WARNING','ERROR','CRITICAL'].forEach(function(lv) {
                    html += '<option value="' + lv + '"' + (String(val).toUpperCase() === lv ? ' selected' : '') + '>' + lv + '</option>';
                });
                html += '</select>';
            } else if (key === 'device') {
                html += '<select id="' + inputId + '" class="glass-input" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                ['cpu','cuda','mps','auto'].forEach(function(d) {
                    html += '<option value="' + d + '"' + (String(val) === d ? ' selected' : '') + '>' + d + '</option>';
                });
                html += '</select>';
            } else if (isBool) {
                html += '<select id="' + inputId + '" class="glass-input" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                html += '<option value="true"' + (val === true ? ' selected' : '') + '>true</option>';
                html += '<option value="false"' + (val === false ? ' selected' : '') + '>false</option>';
                html += '</select>';
            } else {
                var inputType = (typeof val === 'number' && key !== 'host') ? 'number' : 'text';
                html += '<input id="' + inputId + '" type="' + inputType + '" class="glass-input" value="' + esc(String(val)) + '" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + (typeof val === 'number' ? ' step="any"' : '') + '>';
            }

            /* Hot reload badge */
            html += '<span class="setting-badge ' + (hot ? 'badge-hot' : 'badge-restart') + '" title="' + esc(tooltipText) + '">' + (hot ? '⚡ hot' : '🔒 restart') + '</span>';

            /* Status indicator for auto-save fields */
            if (hot) {
                html += '<span class="setting-status" id="status-' + inputId + '"></span>';
            }

            /* Reset button (hidden unless row carries .is-diff) */
            html += '<button class="setting-reset-btn" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '">↩ Reset</button>';

            /* Validation error placeholder */
            html += '<div class="setting-validation-error" role="alert"></div>';

            html += '</div>'; /* end setting-row */
        });

        html += '</div>'; /* end cat-body */
        html += '</div>'; /* end category card */
    });

    /* ── Action buttons ── */
    html += '<div class="glass p-6">';
    html += '<div class="settings-actions">';
    html += '<button id="export-config-btn" class="glass-btn-success glass-btn"><i data-lucide="download"></i> Export Config</button>';
    html += '<button id="reset-config-btn" class="glass-btn-danger glass-btn"><i data-lucide="trash-2"></i> Reset All to Defaults</button>';
    html += '</div>';
    html += '</div>';

    /* ── Global Apply for restart-required changes ── */
    html += '<div class="global-apply-section">';
    html += '<button id="global-apply-btn" class="primary-btn global-apply-btn" disabled><i data-lucide="save"></i> Apply Restart-Required Changes</button>';
    html += '<span id="global-apply-status" class="setting-status"></span>';
    html += '<div id="global-apply-details" class="global-apply-details"></div>';
    html += '</div>';

    safeSetHTML(el, html);

    /* ═══════════════════════ EVENT BINDING ═══════════════════════ */

    /* Save profile button */
    var saveProfileBtn = document.getElementById('save-profile-btn');
    if (saveProfileBtn) saveProfileBtn.onclick = N.Features.Settings.saveSettingsProfile;

    /* Search input (CSP-safe: bound here, no inline oninput) */
    var searchInput = document.getElementById('settings-search');
    if (searchInput) searchInput.addEventListener('input', function() {
        N.Features.Settings.filterSettings(this.value);
    });

    /* Search clear button */
    var searchClearBtn = document.getElementById('settings-search-clear');
    if (searchClearBtn) searchClearBtn.onclick = function() {
        document.getElementById('settings-search').value = '';
        N.Features.Settings.filterSettings('');
    };

    /* Category toggle buttons */
    document.querySelectorAll('.cat-toggle-btn').forEach(function(btn) {
        btn.onclick = function() { N.Features.Settings.toggleCategory(this.dataset.toggleCat); };
    });

    /* Category reset buttons */
    document.querySelectorAll('.cat-reset-btn').forEach(function(btn) {
        btn.onclick = function() { N.Features.Settings.resetCategory(this.dataset.resetCat); };
    });

    /* Per-field reset buttons */
    document.querySelectorAll('.setting-reset-btn').forEach(function(btn) {
        btn.onclick = function() {
            var cat = this.dataset.cat;
            var key = this.dataset.key;
            var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
            if (meta && meta.default_value != null) N.Features.Settings.resetField(cat, key, meta.default_value);
        };
    });

    /* Password toggle buttons */
    document.querySelectorAll('.pw-toggle-btn').forEach(function(btn) {
        btn.onclick = function() {
            var input = document.getElementById(this.dataset.input);
            if (!input) return;
            var isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            safeSetHTML(this, isPassword ? '<i data-lucide="eye-off"></i>' : '<i data-lucide="eye"></i>');
            if (typeof lucide !== 'undefined') lucide.createIcons();
        };
    });

    /* ═══════════════════════ GLOBAL APPLY (restart-required) ═══════════════════════ */
    (function initGlobalApply() {
        var dirtyFields = {};
        var btn = document.getElementById('global-apply-btn');
        var statusEl = document.getElementById('global-apply-status');
        var detailsEl = document.getElementById('global-apply-details');
        if (!btn) return;

        function updateBtnState() {
            var count = Object.keys(dirtyFields).length;
            if (count > 0) {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
                safeSetHTML(btn, '<i data-lucide="save"></i> Apply ' + count + ' Change' + (count > 1 ? 's' : ''));
            } else {
                btn.disabled = true;
                btn.style.opacity = '0.4';
                btn.style.cursor = 'not-allowed';
                safeSetHTML(btn, '<i data-lucide="save"></i> Apply Restart-Required Changes');
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        /* Attach change listeners to all restart-required fields */
        document.querySelectorAll('.setting-row input:not([data-autosave]), .setting-row select:not([data-autosave])').forEach(function(input) {
            if (input.dataset.cat && input.dataset.key) {
                var cat = input.dataset.cat;
                var key = input.dataset.key;
                var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
                if (meta && meta.hot_reload === false) {
                    input.addEventListener('change', function() {
                        var value = this.value;
                        if (this.tagName === 'SELECT') {
                            if (value === 'true') value = true;
                            else if (value === 'false') value = false;
                        } else if (this.type === 'number') {
                            value = parseFloat(value);
                        }
                        var result = N.Features.Settings.validateField(cat, key, value, meta);
                        if (result.valid) {
                            dirtyFields[cat + '.' + key] = { cat: cat, key: key, value: value, inputId: this.id };
                        } else {
                            delete dirtyFields[cat + '.' + key];
                        }
                        updateBtnState();
                    });
                }
            }
        });

        btn.addEventListener('click', async function() {
            var _failedKeys;
            var entries = Object.values(dirtyFields);
            if (entries.length === 0) return;
            btn.disabled = true;
            safeSetHTML(btn, '<span class="setting-spinner"></span> Applying...');
            if (statusEl) { statusEl.className = 'setting-status status-saving visible'; safeSetHTML(statusEl, '<span class="setting-spinner"></span> Saving...'); }
            if (detailsEl) { detailsEl.style.display = 'none'; detailsEl.textContent = ''; }

            var saved = 0, failed = 0, restartNeeded = false;
            for (var i = 0; i < entries.length; i++) {
                var e = entries[i];
                try {
                    var resp = await api('/api/settings', { method: 'PUT', body: JSON.stringify({ category: e.cat, key: e.key, value: e.value }) });
                    saved++;
                    if (resp.restart_required) restartNeeded = true;
                    /* Update internal data */
                    if (S.settingsData && S.settingsData[e.cat] && S.settingsData[e.cat][e.key]) {
                        S.settingsData[e.cat][e.key].value = e.value;
                        S.settingsData[e.cat][e.key].source = 'override';
                    }
                    /* Update source badge */
                    var row = document.getElementById(e.inputId) ? document.getElementById(e.inputId).closest('.setting-row') : null;
                    if (row) {
                        var srcEl = row.querySelector('.setting-source');
                        if (srcEl) {
                            srcEl.className = 'setting-source source-override';
                            srcEl.title = 'Set via WebUI override';
                            safeSetHTML(srcEl, '<i data-lucide="edit-3"></i> override');
                        }
                    }
                } catch (err) {
                    failed++;
                    var catKey = e.cat + '.' + e.key;
                    console.warn('[settings] save failed:', catKey, err.message || err);
                    if (!_failedKeys) _failedKeys = [];
                    _failedKeys.push(catKey);
                }
            }

            if (failed > 0) {
                var failKeys = (_failedKeys || []).slice();
                _failedKeys = null;
                if (statusEl) { statusEl.className = 'setting-status status-error visible'; safeSetHTML(statusEl, '✕ ' + failed + ' failed'); }
                if (failKeys.length > 3) {
                    console.group('[settings] batch save failures');
                    console.table(failKeys.map(function(k) { return { key: k }; }));
                    console.groupEnd();
                }
                toast('<i data-lucide="alert-triangle"></i> ' + failed + ' failed: ' + failKeys.join(', '), 'error');
            } else if (restartNeeded) {
                if (statusEl) { statusEl.className = 'setting-status status-saved visible'; safeSetHTML(statusEl, '✓ Saved — restart to apply'); }
                if (detailsEl) {
                    detailsEl.style.display = 'block';
                    detailsEl.textContent = 'Changes saved. Server restart is required for: ' + entries.map(function(e) { return e.key; }).join(', ');
                    detailsEl.style.color = 'var(--accent-orange)';
                }
            } else {
                if (statusEl) { statusEl.className = 'setting-status status-saved visible'; safeSetHTML(statusEl, '✓ All saved'); }
            }

            toast(restartNeeded
                ? '<i data-lucide="alert-triangle"></i> Changes saved. Server restart required.'
                : '<i data-lucide="check-circle"></i> All changes saved.', restartNeeded ? 'warning' : 'success');

            dirtyFields = {};
            updateBtnState();
            setTimeout(function() {
                if (statusEl) statusEl.classList.remove('visible');
            }, 3000);
        });
    })();

    /* Input validation listeners + auto-save trigger */
    document.querySelectorAll('.setting-row input, .setting-row select').forEach(function(input) {
        input.addEventListener('input', function() {
            var cat = this.dataset.cat;
            var key = this.dataset.key;
            var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
            if (!meta) return;
            var result = N.Features.Settings.validateField(cat, key, this.value, meta);
            var errEl = this.closest('.setting-row').querySelector('.setting-validation-error');
            if (!result.valid) {
                this.style.borderColor = 'var(--accent-red)';
                if (errEl) { errEl.textContent = result.error; errEl.style.display = 'block'; }
            } else {
                this.style.borderColor = '';
                if (errEl) { errEl.textContent = ''; errEl.style.display = 'none'; }
            }
        });

        /* Auto-save on change for hot_reload fields */
        if (input.dataset.autosave === 'true') {
            input.addEventListener('change', function() {
                var cat = this.dataset.cat;
                var key = this.dataset.key;
                var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
                if (!meta) return;
                var value = this.value;
                /* Q9: masked secrets — never resend mask placeholders, enforce min length */
                if (this.dataset.masked === 'true') {
                    if (value === '***' || value.indexOf('•') !== -1) return;
                    if (value !== '' && value.length < 16) {
                        var errEl = this.closest('.setting-row').querySelector('.setting-validation-error');
                        this.style.borderColor = 'var(--accent-red)';
                        if (errEl) { errEl.textContent = 'Minimum 16 characters (empty clears the key).'; errEl.style.display = 'block'; }
                        return;
                    }
                }
                if (this.tagName === 'SELECT') {
                    if (value === 'true') value = true;
                    else if (value === 'false') value = false;
                } else if (this.type === 'number') {
                    value = parseFloat(value);
                }
                var result = N.Features.Settings.validateField(cat, key, value, meta);
                if (!result.valid) return;
                N.Features.Settings.debounceAutoSave(cat, key, this.id, value);
            });
        }
    });

    /* Export button */
    var expBtn = document.getElementById('export-config-btn');
    if (expBtn) expBtn.onclick = function() {
        var blob = new Blob([JSON.stringify(settings, null, 2)], {type: 'application/json'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'nous-config.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        /* Revoke the object URL — no Blob leak */
        setTimeout(function() { try { URL.revokeObjectURL(url); } catch (_) {} }, 1000);
        toast('<i data-lucide="download"></i> Config exported', 'success');
    };

    /* Reset All button */
    var rstBtn = document.getElementById('reset-config-btn');
    if (rstBtn) rstBtn.onclick = async function() {
        if (!confirm('Reset ALL settings to defaults? This cannot be undone.')) return;
        try {
            var count = 0;
            for (const [rCat, rFields] of Object.entries(settings)) {
                if (typeof rFields !== 'object') continue;
                for (const [rKey, rMeta] of Object.entries(rFields)) {
                    if (rMeta && rMeta.source === 'override' && rMeta.default_value != null) {
                        await api('/api/settings', { method: 'PUT', body: JSON.stringify({ category: rCat, key: rKey, value: rMeta.default_value }) });
                        count++;
                    }
                }
            }
            toast('<i data-lucide="check-circle"></i> All settings reset to defaults (' + count + ' changes)', 'success');
            setTimeout(function() { N.Features.Settings.loadSettings(); }, 500);
        } catch (e) {
            toast('<i data-lucide="x-circle"></i> Reset failed: ' + e.message, 'error');
        }
    };

    /* Profile event delegation */
    var profilesList = document.getElementById('profiles-list');
    if (profilesList) {
        profilesList.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-profile-action]');
            if (!btn) return;
            var action = btn.dataset.profileAction;
            var name = btn.dataset.profileName;
            if (action === 'load-builtin') {
                N.Features.Settings.loadSettingsProfile(name, N.Features.Settings.BUILTIN_PROFILES[name]);
            } else if (action === 'load-user') {
                var data = localStorage.getItem('nous_profile_' + name);
                if (data) N.Features.Settings.loadSettingsProfile(name, JSON.parse(data));
            } else if (action === 'delete') {
                N.Features.Settings.deleteSettingsProfile(name);
            }
        });
    }

    N.Features.Settings.renderSettingsProfiles();
    N.Core.animateCards(el);
}

// filterSettings, toggleCategory, sourceIcon → settings-ui.js

Object.assign(N.Features.Settings, {
    renderSettings: renderSettings,
});
})();
