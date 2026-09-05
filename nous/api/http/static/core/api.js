/* =================================================================
   API HELPER
   ================================================================= */
;(function(N) {

N.Core.api = async function api(path, opts) {
  opts = opts || {};
  /* Default 30s timeout unless caller passes its own signal */
  var signal = opts.signal;
  if (!signal && typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    try { signal = AbortSignal.timeout(30000); } catch (_) { signal = undefined; }
  }
  try {
    var resp = await fetch(path, {
      headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
      method: opts.method,
      body: opts.body,
      signal: signal,
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { error: resp.statusText }; });
      throw new Error(err.error || resp.statusText);
    }
    /* JSON guard: only parse as JSON when the server says it is JSON */
    var ctype = "";
    try { ctype = resp.headers ? (resp.headers.get("content-type") || "") : ""; } catch (_) {}
    if (ctype && ctype.indexOf("application/json") === -1) {
      var text = await resp.text();
      throw new Error("Expected JSON, got " + (ctype.split(";")[0] || "unknown") + ": " + String(text).slice(0, 120));
    }
    return await resp.json();
  } catch (e) {
    console.error("API error:", path, e);
    var detail = { path: path, message: e.message, error: e };
    /* Global hook */
    if (typeof N.Core.api._onError === "function") {
      N.Core.api._onError(detail);
    }
    /* Dispatch custom event for loose coupling */
    try {
      window.dispatchEvent(new CustomEvent("api:error", { detail: detail }));
    } catch (_) {}
    throw e;
  }
};

/* Default error hook */
N.Core.api._onError = null;

})(window.Nous);
