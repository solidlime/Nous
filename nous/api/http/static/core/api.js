/* =================================================================
   API HELPER
   ================================================================= */
;(function(N) {

N.Core.api = async function api(path, opts) {
  opts = opts || {};
  try {
    var resp = await fetch(path, {
      headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
      method: opts.method,
      body: opts.body,
      signal: opts.signal,
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { error: resp.statusText }; });
      throw new Error(err.error || resp.statusText);
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

window.api = N.Core.api;
})(window.Nous);
