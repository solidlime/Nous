/* =================================================================
   ADAPTER — Backward-compatible global aliases
   Routes existing global function calls to Nous.Core.* equivalents.
   Remove this file after Phase 9 when all files use Nous.* directly.
   ================================================================= */
;(function(N) {
"use strict";

// Utilities
window.esc = N.Core.esc;
window.truncate = N.Core.truncate;
window.relativeTime = N.Core.relativeTime;
window.fmtDate = N.Core.fmtDate;
window.api = N.Core.api;

// UI
window.toast = N.Core.toast;
window.showConfirm = N.Core.showConfirm;
window.showAlert = N.Core.showAlert;
window.applyTheme = N.Core.applyTheme;
window.toggleTheme = N.Core.toggleTheme;
window.connectSSE = N.Core.connectSSE;

// Constants (preserve global copies for backward compat)
window.CHART_COLORS = N.Core.CHART_COLORS;
window.EMOTION_COLORS = N.Core.EMOTION_COLORS;
window.EMOTION_BAR_COLORS = N.Core.EMOTION_BAR_COLORS;
window.BODY_BAR_COLORS = N.Core.BODY_BAR_COLORS;
window.BODY_LABELS = N.Core.BODY_LABELS;

})(window.Nous);
