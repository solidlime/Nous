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
    var method = (opts.method || "GET").toUpperCase();
    var headers = Object.assign({}, opts.headers || {});
    /* GET/HEAD carry no body — a JSON Content-Type is meaningless there and
       can trip strict CORS preflight / proxy handling. */
    if (method !== "GET" && method !== "HEAD" &&
        !headers["Content-Type"] && !headers["content-type"]) {
      headers["Content-Type"] = "application/json";
    }
    var resp = await fetch(path, {
      headers: headers,
      method: opts.method,
      body: opts.body,
      signal: signal,
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { error: resp.statusText }; });
      var httpErr = new Error(err.error || resp.statusText);
      /* Tag the HTTP status so callers can special-case expected states
         (e.g. 409 turn-already-running) without parsing the message. */
      httpErr.status = resp.status;
      throw httpErr;
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
    /* Cancel/timeout aborts are not user-facing failures — skip the global
       hook + api:error toast so navigation/timeout races don't flash a toast. */
    if (e && (e.name === "AbortError" || e.name === "TimeoutError")) {
      throw e;
    }
    var detail = { path: path, message: e.message, error: e };
    /* Callers may opt out of the global toast for expected failures
       (e.g. a background lookup of a memory key that no longer exists). */
    if (!opts.suppressErrorToast) {
      /* Global hook */
      if (typeof N.Core.api._onError === "function") {
        N.Core.api._onError(detail);
      }
      /* Dispatch custom event for loose coupling */
      try {
        window.dispatchEvent(new CustomEvent("api:error", { detail: detail }));
      } catch (_) {}
    }
    throw e;
  }
};

/* Default error hook */
N.Core.api._onError = null;

})(window.Nous);
