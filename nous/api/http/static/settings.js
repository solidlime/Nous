;(function() {
var S = window.S;
/* ═══════════════════════════════════════════════════════════════════
   SETTINGS DASHBOARD — Nous WebUI
   ═══════════════════════════════════════════════════════════════════ */

var { esc, toast, api } = window.Nous.Core;

const BUILTIN_PROFILES = {
    'Development': {
        server: { host: '0.0.0.0', port: 26262 },
        embedding: { model: 'onnx-community/ruri-v3-30m-ONNX', device: 'cpu' },
        reranker: { model: 'hotchpotch/japanese-reranker-xsmall-v2', enabled: true },
        general: { log_level: 'DEBUG', contradiction_threshold: 0.85, duplicate_threshold: 0.90 },
        forgetting: { enabled: true, decay_interval_seconds: 3600, min_strength: 0.005, emotion_half_life_hours: 24.0 }
    },
    'Production': {
        embedding: { model: 'onnx-community/ruri-v3-30m-ONNX', device: 'auto' },
        reranker: { model: 'hotchpotch/japanese-reranker-xsmall-v2', enabled: true },
        general: { log_level: 'WARNING', contradiction_threshold: 0.85, duplicate_threshold: 0.90 },
        forgetting: { enabled: true, decay_interval_seconds: 1800, min_strength: 0.005, emotion_half_life_hours: 24.0 }
    }
};

const CATEGORY_ICONS = {
    server: '<i data-lucide="monitor"></i>',
    embedding: '<i data-lucide="brain"></i>',
    reranker: '<i data-lucide="search"></i>',
    qdrant: '<i data-lucide="package"></i>',
    forgetting: '<i data-lucide="eraser"></i>',
    memory_enrichment: '<i data-lucide="sparkles"></i>',
    auto_capture: '<i data-lucide="camera"></i>',
    memorag: '<i data-lucide="layers"></i>',
    general: '<i data-lucide="settings"></i>'
};

const CATEGORY_DESCRIPTIONS = {
    server: 'Server bind address and port. Changes require a full server restart.',
    embedding: 'Embedding model configuration for vector search. Reload takes 10-60s.',
    reranker: 'Cross-encoder reranker for search result quality. Reload takes 5-30s.',
    qdrant: 'Qdrant vector database connection settings.',
    forgetting: 'Ebbinghaus forgetting curve for automatic memory decay.',
    memory_enrichment: 'Auto-evaluate importance and relations via LLM after memory creation.',
    auto_capture: '自動メモリキャプチャ設定',
    memorag: 'MemoRAG設定',
    general: 'General settings: timezone, logging, thresholds, search engine.'
};

/* ── Category display order (consistent across renders) ── */
const CATEGORY_ORDER = [
    'general', 'server', 'embedding', 'reranker',
    'qdrant', 'forgetting', 'memory_enrichment',
    'auto_capture', 'memorag'
];

/* ═══════════════════════════════════════════════════════════════════
   AUTO-SAVE DEBOUNCE & HELPERS
   ═══════════════════════════════════════════════════════════════════ */

const _autoSaveTimers = {};
const RELOAD_CATEGORIES = new Set(['embedding', 'reranker', 'qdrant']);

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
    statusEl.innerHTML = '<span class="setting-spinner"></span> Saving...';

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
        statusEl.innerHTML = '✓ Saved';

        /* Update source badge to "override" */
        if (row) {
            var srcEl = row.querySelector('.setting-source');
            if (srcEl) {
                srcEl.className = 'setting-source source-override';
                srcEl.title = 'Set via WebUI override';
                srcEl.innerHTML = '<i data-lucide="edit-3"></i> override';
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
            statusEl.innerHTML = '<span class="setting-spinner reloading"></span> Reloading...';
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
        statusEl.innerHTML = '✕ Error';
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
   LOAD SETTINGS
   ═══════════════════════════════════════════════════════════════════ */

async function loadSettings() {
    const el = document.getElementById('settings-content');
    try {
        const [resp, status] = await Promise.all([
            api('/api/settings'),
            api('/api/settings/status')
        ]);
        const settingsData = resp.settings || resp;
        S.settingsData = settingsData;
        S.settingsReloadStatus = status;
        renderSettings(el, settingsData, status);
        updateLastTime();
    } catch (e) {
        el.innerHTML = errorCard('Failed to load settings: ' + e.message);
    }
}

/* ═══════════════════════════════════════════════════════════════════
   SOURCE ICON
   ═══════════════════════════════════════════════════════════════════ */

function sourceIcon(src) {
    if (src === 'env') return '<span class="setting-source source-env" title="Set via environment variable"><i data-lucide="globe"></i> env</span>';
    if (src === 'override') return '<span class="setting-source source-override" title="Set via WebUI override"><i data-lucide="edit-3"></i> override</span>';
    return '<span class="setting-source source-default" title="Using default value"><i data-lucide="clipboard-list"></i> default</span>';
}

/* ═══════════════════════════════════════════════════════════════════
   RENDER SETTINGS
   ═══════════════════════════════════════════════════════════════════ */

function renderSettings(el, settings, status) {
    var reloadStatus = (status && status.reload_status) || {};
    var html = '';

    /* ── Profiles section ── */
    html += '<div class="glass p-4 mb-6">';
    html += '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">';
    html += '<h3 style="font-size:1rem;font-weight:600;color:var(--text-primary)"><i data-lucide="clipboard-list"></i> Settings Profiles</h3>';
    html += '<button id="save-profile-btn" class="glass-btn" style="padding:6px 14px;font-size:0.8rem"><i data-lucide="save"></i> Save Current as Profile</button>';
    html += '</div>';
    html += '<div id="profiles-list" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px"></div>';
    html += '</div>';

    /* ── Search bar ── */
    html += '<div class="glass p-4 mb-6" style="position:sticky;top:120px;z-index:30">';
    html += '<div style="position:relative">';
    html += '<span style="position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--text-muted);font-size:0.9rem"><i data-lucide="search"></i></span>';
    html += '<input id="settings-search" type="text" class="glass-input" placeholder="Search settings..." style="width:100%;padding-left:38px;padding-right:36px;font-size:0.9rem" oninput="filterSettings(this.value)">';
    html += '<button id="settings-search-clear" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.85rem;display:none" onclick="document.getElementById(\'settings-search\');filterSettings(\'\')"><i data-lucide="x"></i></button>';
    html += '</div>';
    html += '</div>';

    /* ── Category cards ── */
    var sortedCats = CATEGORY_ORDER.filter(function(c) { return settings[c]; });
    /* Append any categories not in CATEGORY_ORDER (future-proofing) */
    Object.keys(settings).forEach(function(c) {
        if (c !== 'reload_status' && sortedCats.indexOf(c) === -1) sortedCats.push(c);
    });

    sortedCats.forEach(function(cat) {
        var fields = settings[cat];
        if (typeof fields !== 'object' || fields === null) return;
        var hasFields = Object.values(fields).some(function(f) { return typeof f === 'object' && f !== null; });
        if (!hasFields) return;

        var icon = CATEGORY_ICONS[cat] || '<i data-lucide="settings"></i>';
        var catLabel = cat.replace(/_/g, ' ').replace(/\b\w/g, function(l) { return l.toUpperCase(); });
        var catDesc = CATEGORY_DESCRIPTIONS[cat] || '';

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
                statusHtml = '<div style="margin-top:8px"><div style="font-size:0.78rem;color:var(--accent-yellow);margin-bottom:4px"><i data-lucide="clock"></i> ' + esc(catStatus.message || 'Loading...') + '</div><div class="progress-wrap"><div class="progress-bar progress-indeterminate"></div></div></div>';
            } else if (st === 'ready' || st === 'success') {
                statusHtml = '<div style="margin-top:8px;font-size:0.78rem;color:var(--accent-green)"><i data-lucide="check-circle"></i> ' + esc(catStatus.message || 'Ready') + '</div>';
            } else if (st === 'error') {
                statusHtml = '<div style="margin-top:8px;font-size:0.78rem;color:var(--accent-red)"><i data-lucide="x-circle"></i> ' + esc(catStatus.message || 'Error') + '</div>';
            }
        }

        /* Card wrapper */
        html += '<div class="glass p-6 mb-6 setting-category-card" data-category="' + esc(cat) + '" data-searchtext="' + esc(catSearchText) + '">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:4px">';
        html += '<div style="display:flex;align-items:center;gap:10px">';
        html += '<button class="cat-toggle-btn" id="cat-toggle-' + cat + '" data-toggle-cat="' + cat + '" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.8rem;padding:2px" title="Toggle section">▼</button>';
        html += '<span class="card-title" style="margin:0">' + icon + ' ' + esc(catLabel) + '</span>';
        html += '</div>';
        html += '<div style="display:flex;align-items:center;gap:8px">';
        if (hasDiffs) {
            html += '<button class="cat-reset-btn" data-reset-cat="' + cat + '" style="font-size:0.75rem;padding:4px 10px;border-radius:8px;background:rgba(248,113,113,0.1);border:1px solid rgba(248,113,113,0.3);color:var(--accent-red);cursor:pointer">↩ Reset Category</button>';
        }
        html += '</div>';
        html += '</div>';

        /* Category description */
        if (catDesc) {
            html += '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:12px;line-height:1.4;padding-left:22px">' + esc(catDesc) + '</div>';
        }

        html += statusHtml;
        html += '<div id="cat-body-' + cat + '" class="cat-body">';

        /* ── Fields ── */
        Object.entries(fields).forEach(function(entry) {
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
                ? '<i data-lucide="refresh-cw" style="width:13px;height:13px"></i> Hot-reload'
                : '<i data-lucide="lock" style="width:13px;height:13px"></i> Restart required';
            var tooltipText = reloadHint + (meta.reload_time ? ' (' + meta.reload_time + ')' : '');
            var searchText = key.replace(/_/g, ' ') + ' ' + desc + ' ' + cat;

            html += '<div class="setting-row" data-setting-key="' + cat + '.' + key + '" data-category="' + cat + '" data-searchtext="' + esc(searchText) + '">';

            /* Label column with diff dot */
            html += '<div style="display:flex;flex-direction:column;gap:2px;flex:0 0 auto;min-width:160px;position:relative">';
            html += '<span class="setting-diff-dot" style="' + (isDiff ? '' : 'display:none;') + 'position:absolute;left:-14px;top:8px;width:8px;height:8px;border-radius:50%;background:var(--accent-blue)"></span>';
            html += '<label class="setting-label" for="' + inputId + '" title="' + esc(tooltipText) + '" style="margin-bottom:0">' + esc(key.replace(/_/g, ' ')) + '</label>';
            if (desc) html += '<span style="font-size:0.7rem;color:var(--text-muted);line-height:1.3">' + esc(desc) + '</span>';
            html += '</div>';

            /* Source icon */
            html += sourceIcon(src);

            /* Input element */
            var autosaveAttr = hot ? ' data-autosave="true"' : '';
            if (isMasked) {
                /* ── Password / masked field with toggle ── */
                var displayVal = isMasked && val === '***' ? '••••••••' : String(val);
                html += '<div style="flex:1;min-width:160px;position:relative;display:flex;align-items:center">';
                html += '<input id="' + inputId + '" type="password" class="glass-input" style="flex:1;padding-right:36px" value="' + esc(String(val)) + '" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '" data-masked="true"' + autosaveAttr + ' placeholder="' + (val === '***' ? '•••••••• (set via env/override)' : 'Enter value...') + '"' + (!hot ? ' disabled' : '') + '>';
                html += '<button class="pw-toggle-btn" data-input="' + inputId + '" style="position:absolute;right:8px;background:none;border:none;color:var(--text-muted);cursor:pointer;padding:2px;font-size:0.8rem" title="Show/hide"><i data-lucide="eye"></i></button>';
                html += '</div>';
            } else if (key === 'log_level') {
                html += '<select id="' + inputId + '" class="glass-input" style="flex:1;min-width:120px" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                ['DEBUG','INFO','WARNING','ERROR','CRITICAL'].forEach(function(lv) {
                    html += '<option value="' + lv + '"' + (String(val).toUpperCase() === lv ? ' selected' : '') + '>' + lv + '</option>';
                });
                html += '</select>';
            } else if (key === 'device') {
                html += '<select id="' + inputId + '" class="glass-input" style="flex:1;min-width:120px" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                ['cpu','cuda','mps','auto'].forEach(function(d) {
                    html += '<option value="' + d + '"' + (String(val) === d ? ' selected' : '') + '>' + d + '</option>';
                });
                html += '</select>';
            } else if (isBool) {
                html += '<select id="' + inputId + '" class="glass-input" style="flex:1;min-width:120px" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + '">';
                html += '<option value="true"' + (val === true ? ' selected' : '') + '>true</option>';
                html += '<option value="false"' + (val === false ? ' selected' : '') + '>false</option>';
                html += '</select>';
            } else {
                var inputType = (typeof val === 'number' && key !== 'host') ? 'number' : 'text';
                html += '<input id="' + inputId + '" type="' + inputType + '" class="glass-input" style="flex:1;min-width:160px" value="' + esc(String(val)) + '" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '"' + autosaveAttr + (typeof val === 'number' ? ' step="any"' : '') + (!hot ? ' disabled' : '') + '>';
            }

            /* Hot reload badge */
            html += '<span class="setting-badge ' + (hot ? 'badge-hot' : 'badge-restart') + '" title="' + esc(tooltipText) + '">' + (hot ? '⚡ hot' : '🔒 restart') + '</span>';

            /* Status indicator for auto-save fields */
            if (hot) {
                html += '<span class="setting-status" id="status-' + inputId + '"></span>';
            }

            /* Reset button (hidden when no diff) */
            html += '<button class="setting-reset-btn" data-cat="' + esc(cat) + '" data-key="' + esc(key) + '" style="' + (isDiff ? '' : 'display:none;') + 'padding:4px 10px;font-size:0.72rem;background:none;border:1px solid var(--glass-border);border-radius:6px;color:var(--text-muted);cursor:pointer">↩ Reset</button>';

            /* Validation error placeholder */
            html += '<div class="setting-validation-error" style="display:none;width:100%;font-size:0.72rem;color:var(--accent-red);margin-top:2px"></div>';

            html += '</div>'; /* end setting-row */
        });

        html += '</div>'; /* end cat-body */
        html += '</div>'; /* end category card */
    });

    /* ── Source legend & action buttons ── */
    html += '<div class="glass p-6">';
    html += '<div class="card-title"><i data-lucide="info"></i> Configuration Source Priority</div>';
    html += '<div style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:16px">';
    html += '<span class="setting-source source-env"><i data-lucide="globe"></i> env</span>';
    html += '<span style="margin:0 8px;color:var(--text-muted)">&gt;</span>';
    html += '<span class="setting-source source-override"><i data-lucide="edit-3"></i> override</span>';
    html += '<span style="margin:0 8px;color:var(--text-muted)">&gt;</span>';
    html += '<span class="setting-source source-default"><i data-lucide="clipboard-list"></i> default</span>';
    html += '</div>';
    html += '<div style="display:flex;gap:10px;flex-wrap:wrap">';
    html += '<button id="export-config-btn" class="glass-btn-success glass-btn"><i data-lucide="download"></i> Export Config</button>';
    html += '<button id="reset-config-btn" class="glass-btn-danger glass-btn"><i data-lucide="trash-2"></i> Reset All to Defaults</button>';
    html += '</div>';
    html += '</div>';

    /* ── Global Apply for restart-required changes ── */
    html += '<div class="global-apply-section">';
    html += '<button id="global-apply-btn" class="primary-btn" disabled style="padding:10px 24px;font-size:0.85rem;font-weight:600;border-radius:10px;background:linear-gradient(135deg,rgba(var(--accent-blue-rgb),0.2),rgba(var(--accent-teal-rgb),0.2));border:1px solid rgba(var(--accent-blue-rgb),0.3);color:var(--text-primary);cursor:not-allowed;opacity:0.4;transition:all 0.2s"><i data-lucide="save"></i> Apply Restart-Required Changes</button>';
    html += '<span id="global-apply-status" class="setting-status"></span>';
    html += '<div id="global-apply-details" style="display:none;width:100%;margin-top:8px;font-size:0.78rem;color:var(--text-muted)"></div>';
    html += '</div>';

    el.innerHTML = html;

    /* ═══════════════════════ EVENT BINDING ═══════════════════════ */

    /* Save profile button */
    var saveProfileBtn = document.getElementById('save-profile-btn');
    if (saveProfileBtn) saveProfileBtn.onclick = saveSettingsProfile;

    /* Search clear button */
    var searchClearBtn = document.getElementById('settings-search-clear');
    if (searchClearBtn) searchClearBtn.onclick = function() {
        document.getElementById('settings-search').value = '';
        filterSettings('');
    };

    /* Category toggle buttons */
    document.querySelectorAll('.cat-toggle-btn').forEach(function(btn) {
        btn.onclick = function() { toggleCategory(this.dataset.toggleCat); };
    });

    /* Category reset buttons */
    document.querySelectorAll('.cat-reset-btn').forEach(function(btn) {
        btn.onclick = function() { resetCategory(this.dataset.resetCat); };
    });

    /* Per-field reset buttons */
    document.querySelectorAll('.setting-reset-btn').forEach(function(btn) {
        btn.onclick = function() {
            var cat = this.dataset.cat;
            var key = this.dataset.key;
            var meta = S.settingsData && S.settingsData[cat] && S.settingsData[cat][key];
            if (meta && meta.default_value != null) resetField(cat, key, meta.default_value);
        };
    });

    /* Password toggle buttons */
    document.querySelectorAll('.pw-toggle-btn').forEach(function(btn) {
        btn.onclick = function() {
            var input = document.getElementById(this.dataset.input);
            if (!input) return;
            var isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            this.innerHTML = isPassword ? '<i data-lucide="eye-off"></i>' : '<i data-lucide="eye"></i>';
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
                btn.innerHTML = '<i data-lucide="save"></i> Apply ' + count + ' Change' + (count > 1 ? 's' : '');
            } else {
                btn.disabled = true;
                btn.style.opacity = '0.4';
                btn.style.cursor = 'not-allowed';
                btn.innerHTML = '<i data-lucide="save"></i> Apply Restart-Required Changes';
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        /* Attach change listeners to all restart-required fields */
        document.querySelectorAll('.setting-row input[data-autosave="false"], .setting-row select[data-autosave="false"]').forEach(function(input) {
            /* Skip — these shouldn't exist, but be safe */
        });
        /* restart-required fields have no data-autosave attr and are not hot */
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
                        var result = validateField(cat, key, value, meta);
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
            var entries = Object.values(dirtyFields);
            if (entries.length === 0) return;
            btn.disabled = true;
            btn.innerHTML = '<span class="setting-spinner"></span> Applying...';
            if (statusEl) { statusEl.className = 'setting-status status-saving visible'; statusEl.innerHTML = '<span class="setting-spinner"></span> Saving...'; }
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
                            srcEl.innerHTML = '<i data-lucide="edit-3"></i> override';
                        }
                    }
                } catch (err) {
                    failed++;
                    var catKey = e.cat + '.' + e.key;
                    console.warn('[settings] save failed:', catKey, err.message || err);
                    /* Accumulate failed key paths */
                    if (!window.__settings_failed_keys) window.__settings_failed_keys = [];
                    window.__settings_failed_keys.push(catKey);
                }
            }

            if (failed > 0) {
                var failKeys = (window.__settings_failed_keys || []).slice();
                window.__settings_failed_keys = null;
                if (statusEl) { statusEl.className = 'setting-status status-error visible'; statusEl.innerHTML = '✕ ' + failed + ' failed'; }
                /* Log batch failures in a structured way */
                if (failKeys.length > 3) {
                    console.group('[settings] batch save failures');
                    console.table(failKeys.map(function(k) { return { key: k }; }));
                    console.groupEnd();
                }
                toast('<i data-lucide="alert-triangle"></i> ' + failed + ' failed: ' + failKeys.join(', '), 'error');
            } else if (restartNeeded) {
                if (statusEl) { statusEl.className = 'setting-status status-saved visible'; statusEl.innerHTML = '✓ Saved — restart to apply'; }
                if (detailsEl) {
                    detailsEl.style.display = 'block';
                    detailsEl.textContent = 'Changes saved. Server restart is required for: ' + entries.map(function(e) { return e.key; }).join(', ');
                    detailsEl.style.color = 'var(--accent-orange)';
                }
            } else {
                if (statusEl) { statusEl.className = 'setting-status status-saved visible'; statusEl.innerHTML = '✓ All saved'; }
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
            var result = validateField(cat, key, this.value, meta);
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
                /* Type coercion */
                if (this.tagName === 'SELECT') {
                    if (value === 'true') value = true;
                    else if (value === 'false') value = false;
                } else if (this.type === 'number') {
                    value = parseFloat(value);
                }
                /* Validation before save */
                var result = validateField(cat, key, value, meta);
                if (!result.valid) return;
                debounceAutoSave(cat, key, this.id, value);
            });
        }
    });

    /* Export button */
    var expBtn = document.getElementById('export-config-btn');
    if (expBtn) expBtn.onclick = function() {
        var blob = new Blob([JSON.stringify(settings, null, 2)], {type: 'application/json'});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'nous-config.json';
        a.click();
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
            setTimeout(function() { loadSettings(); }, 500);
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
                loadSettingsProfile(name, BUILTIN_PROFILES[name]);
            } else if (action === 'load-user') {
                var data = localStorage.getItem('nous_profile_' + name);
                if (data) loadSettingsProfile(name, JSON.parse(data));
            } else if (action === 'delete') {
                deleteSettingsProfile(name);
            }
        });
    }

    renderSettingsProfiles();
    animateCards(el);
}
window.loadSettings = loadSettings;

/* ═══════════════════════════════════════════════════════════════════
   SEARCH / FILTER
   ═══════════════════════════════════════════════════════════════════ */

function filterSettings(query) {
    var q = query.toLowerCase().trim();
    var clearBtn = document.getElementById('settings-search-clear');
    if (clearBtn) clearBtn.style.display = q ? 'block' : 'none';

    document.querySelectorAll('.setting-category-card').forEach(function(card) {
        var catText = (card.dataset.searchtext || '').toLowerCase();
        var rows = card.querySelectorAll('.setting-row');

        if (!q) {
            card.style.display = '';
            rows.forEach(function(r) { r.style.display = ''; });
            return;
        }

        var catMatch = catText.includes(q);
        var anyRowMatch = false;

        rows.forEach(function(r) {
            var rowText = (r.dataset.searchtext || '').toLowerCase();
            if (catMatch || rowText.includes(q)) {
                r.style.display = '';
                anyRowMatch = true;
            } else {
                r.style.display = 'none';
            }
        });

        card.style.display = (catMatch || anyRowMatch) ? '' : 'none';

        /* Auto-expand matching categories */
        if (catMatch || anyRowMatch) {
            var cat = card.dataset.category;
            var body = document.getElementById('cat-body-' + cat);
            var toggle = document.getElementById('cat-toggle-' + cat);
            if (body) body.style.display = 'block';
            if (toggle) toggle.textContent = '▼';
        }
    });
}
window.filterSettings = filterSettings;

/* ═══════════════════════════════════════════════════════════════════
   CATEGORY TOGGLE
   ═══════════════════════════════════════════════════════════════════ */

function toggleCategory(catId) {
    var body = document.getElementById('cat-body-' + catId);
    var toggle = document.getElementById('cat-toggle-' + catId);
    if (!body || !toggle) return;
    if (body.style.display === 'none') {
        body.style.display = 'block';
        toggle.textContent = '▼';
    } else {
        body.style.display = 'none';
        toggle.textContent = '▶';
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
                statusEl.innerHTML = '✓ Saved';
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
                    srcEl.innerHTML = '<i data-lucide="clipboard-list"></i> default';
                }
            }
            /* Start polling for reload categories */
            if (RELOAD_CATEGORIES.has(cat)) startStatusPoll();
        } else {
            /* Restart-required field: reload to show updated source badge */
            setTimeout(function() { loadSettings(); }, 800);
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
            setTimeout(function() { loadSettings(); }, 800);
        }
    } catch (e) {
        toast('<i data-lucide="x-circle"></i> Reset failed: ' + e.message, 'error');
    }
}

/* ═══════════════════════════════════════════════════════════════════
   FIELD VALIDATION
   ═══════════════════════════════════════════════════════════════════ */

function validateField(cat, key, value, meta) {
    /* Skip validation for empty masked fields (user hasn't entered a new value) */
    if (meta.masked && (!value || value === '••••••••' || value === '***')) {
        return { valid: true, error: '' };
    }
    /* Number validation */
    if (typeof meta.default_value === 'number' || meta.default_value === 0) {
        var num = parseFloat(value);
        if (isNaN(num)) return { valid: false, error: 'Must be a number' };
        if (key === 'port' && (num < 1 || num > 65535)) return { valid: false, error: 'Port must be 1-65535' };
        if (key === 'min_strength' && (num < 0 || num > 1)) return { valid: false, error: 'Must be 0-1' };
        if (key === 'min_importance' && (num < 0 || num > 1)) return { valid: false, error: 'Must be 0-1' };
        if (key === 'contradiction_threshold' && (num < 0 || num > 1)) return { valid: false, error: 'Must be 0-1' };
        if (key === 'duplicate_threshold' && (num < 0 || num > 1)) return { valid: false, error: 'Must be 0-1' };
        if (key.includes('interval') && num < 0) return { valid: false, error: 'Must be >= 0' };
        if (key === 'llm_max_tokens' && num < 1) return { valid: false, error: 'Must be >= 1' };
    }
    /* URL validation */
    if (key.includes('url') && value && !(String(value).startsWith('http://') || String(value).startsWith('https://'))) {
        return { valid: false, error: 'Must start with http:// or https://' };
    }
    return { valid: true, error: '' };
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
        setTimeout(function() { loadSettings(); }, 1000);
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
    /* User profiles from localStorage — collect keys upfront to avoid mixing non-profile keys */
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
    container.innerHTML = html;
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
                            el.innerHTML = '✓ Ready';
                            setTimeout(function() { el.classList.remove('visible'); }, 2000);
                        });
                    } else if (s && s.status === 'error') {
                        document.querySelectorAll('[data-category="' + cat + '"] .setting-status.status-reloading').forEach(function(el) {
                            el.className = 'setting-status status-error visible';
                            el.innerHTML = '✕ Error';
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

/* ── Clean up status polling when leaving the settings tab ── */
document.addEventListener('DOMContentLoaded', function() {
    const origSwitchTab = switchTab;
    if (typeof switchTab !== 'undefined') {
        switchTab = function(tabId) {
            /* Leaving settings tab → stop polling */
            if (S.tab === 'settings' && tabId !== 'settings') {
                if (S.statusPoll) {
                    clearInterval(S.statusPoll);
                    S.statusPoll = null;
                }
            }
            origSwitchTab(tabId);
        };
    }
});

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
                    existing.innerHTML = statusHtml;
                } else {
                    var div = document.createElement('div');
                    div.className = 'cat-reload-status';
                    div.innerHTML = statusHtml;
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
})();
