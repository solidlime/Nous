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
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { error: resp.statusText }; });
      throw new Error(err.error || resp.statusText);
    }
    return await resp.json();
  } catch (e) {
    console.error("API error:", path, e);
    throw e;
  }
};

})(window.Nous);
