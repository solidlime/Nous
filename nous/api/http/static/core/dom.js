/* =================================================================
   DOM HELPERS — Safe HTML escaping, element creation
   ================================================================= */
;(function(N) {

N.Core.esc = function esc(s) {
  if (s === null || s === undefined) return "";
  var d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};

N.Core.truncate = function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + "..." : s || "";
};

var _iconRefreshPending = false;
N.Core.refreshIcons = function() {
  if (typeof lucide === "undefined" || !lucide.createIcons) return;
  if (_iconRefreshPending) return;
  _iconRefreshPending = true;
  requestAnimationFrame(function() {
    _iconRefreshPending = false;
    // Re-guard: lucide CDN may be blocked/absent even if present at call time.
    if (typeof lucide === "undefined" || !lucide.createIcons) return;
    lucide.createIcons();
  });
};

/**
 * Safely set innerHTML via DOMPurify (CSP-safe: no inline handlers allowed).
 * script-src 'self' forbids inline onclick/onchange — use delegation + data-*.
 * Falls back to textContent if DOMPurify is unavailable.
 */
N.Core.safeSetHTML = function safeSetHTML(element, html) {
  if (!element) return;
  if (typeof html !== "string") html = String(html == null ? "" : html);
  if (typeof DOMPurify !== "undefined") {
    element.innerHTML = DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        "i","b","strong","em","span","br","code","pre","div","a","img",
        "p","ul","ol","li","h1","h2","h3","h4","h5","h6","table","thead",
        "tbody","tr","td","th","details","summary","form","input","label","select",
        "option","textarea","button","blockquote","hr","del","ins","sup",
        "sub","dl","dt","dd","abbr","small","mark","wbr","canvas","svg","path",
        "circle","rect","line","polyline","polygon",
      ],
      ALLOWED_ATTR: [
        "class","id","href","src","alt","title","target","rel","data-*",
        "width","height","viewBox","fill","stroke","stroke-width",
        "d","cx","cy","r","x","y","x1","y1","x2","y2","points","transform",
        "aria-*","role","type","value","placeholder","checked","disabled",
        "selected","for","name","required","min","max","step","pattern",
        "autocomplete","rows","cols","readonly","tabindex",
      ],
      FORBID_ATTR: ["style", "onclick", "onchange", "onerror", "onload", "oninput", "onmouseover", "onfocus"],
    });
  } else {
    element.textContent = html;
  }
};

})(window.Nous);
