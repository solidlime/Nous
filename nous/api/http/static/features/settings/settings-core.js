/* =================================================================
   SETTINGS CORE — State, initialization, data loading
   Namespace: N.Features.Settings.*
   Depends on: N.Core.* (api, safeSetHTML)
               N.Features.Settings.renderSettings (settings-form.js)
               window.S
   ================================================================= */
N.Features.Settings = N.Features.Settings || {};

;(function() {
var S = window.S;
var { api, esc, safeSetHTML } = window.Nous.Core;

/* ═══════════════════════════════════════════════════════════════════
   LOAD SETTINGS
   ═══════════════════════════════════════════════════════════════════ */

async function loadSettings() {
    const el = document.getElementById('settings-content');
    N.Components.skeleton.show('settings');
    try {
        const [resp, status] = await Promise.all([
            api('/api/settings'),
            api('/api/settings/status')
        ]);
        const settingsData = resp.settings || resp;
        S.settingsData = settingsData;
        S.settingsReloadStatus = status;
        N.Features.Settings.renderSettings(el, settingsData, status);
        N.Core.updateLastTime();
    } catch (e) {
        console.error('settings load failed:', e);
        safeSetHTML(el, N.Components.skeleton.errorCard('Failed to load settings', function(){ loadSettings(); }));
    }
    loadSecurityDiagnostics();
}

/* 公開運用の危険な設定（公開 bind + 鍵なし / CORS '*' / plugin 鍵不足）を上部に出す。
   診断はサーバの 1 箇所（security_diagnostics）で判定済み。ここは表示だけ。 */
async function loadSecurityDiagnostics() {
    const el = document.getElementById('settings-diagnostics');
    if (!el) return;
    try {
        const data = await api('/api/settings/diagnostics');
        const warnings = (data && data.warnings) || [];
        if (!warnings.length) { safeSetHTML(el, ''); return; }
        const rows = warnings.map(function(w) {
            return '<div style="margin-top:6px;"><strong>' + esc(w.message) + '</strong>' +
                '<div style="color:var(--text-muted); font-size:0.78rem; margin-top:2px;">' + esc(w.hint) + '</div></div>';
        }).join('');
        safeSetHTML(el,
            '<div class="glass p-4" style="margin-bottom:16px; border-left:3px solid var(--accent-orange, #f59e0b);">' +
            '<div style="font-weight:600; color:var(--accent-orange, #f59e0b);">' +
            '公開運用の警告（' + warnings.length + ' 件）</div>' + rows + '</div>');
    } catch (e) {
        console.warn('security diagnostics failed:', e);
        safeSetHTML(el, '');
    }
}
/* N.Features.Settings.loadSettings registered below */

/* ── Clean up status polling when leaving the settings tab ── */
document.addEventListener('DOMContentLoaded', function() {
    const origSwitchTab = N.Core.switchTab;
    if (typeof origSwitchTab === 'function') {
        N.Core.switchTab = function(tabId) {
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

Object.assign(N.Features.Settings, {
    loadSettings: loadSettings,
});
})();
