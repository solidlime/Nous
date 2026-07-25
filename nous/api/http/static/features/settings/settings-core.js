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
var { api, safeSetHTML } = window.Nous.Core;

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
