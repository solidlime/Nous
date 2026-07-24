/* =================================================================
   SETTINGS VALIDATION — Field validation logic
   Namespace: N.Features.Settings.*
   Depends on: nothing (pure function)
   ================================================================= */
N.Features.Settings = N.Features.Settings || {};

;(function() {
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

Object.assign(N.Features.Settings, {
    validateField: validateField,
});
})();
