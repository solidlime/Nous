/* =================================================================
   DOM HELPERS — Safe HTML escaping, element creation
   ================================================================= */
;(function(N) {

N.Core.esc = function esc(s) {
  if (!s) return "";
  var d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML.replace(/"/g, "&quot;");
};

N.Core.truncate = function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + "..." : s || "";
};

var _iconRefreshPending = false;
N.Core.refreshIcons = function() {
  if (_iconRefreshPending) return;
  _iconRefreshPending = true;
  requestAnimationFrame(function() {
    lucide.createIcons();
    _iconRefreshPending = false;
  });
};

window.esc = N.Core.esc;
window.truncate = N.Core.truncate;

/**
 * Safely set innerHTML via DOMPurify.
 * Falls back to textContent if DOMPurify is unavailable.
 */
N.Core.safeSetHTML = function safeSetHTML(element, html) {
  if (typeof DOMPurify !== "undefined") {
    element.innerHTML = DOMPurify.sanitize(html, {
      ALLOWED_TAGS: [
        "i","b","strong","em","span","br","code","pre","div","a","img",
        "p","ul","ol","li","h1","h2","h3","h4","h5","h6","table","thead",
        "tbody","tr","td","th","details","summary","input","label","select",
        "option","textarea","button","blockquote","hr","del","ins","sup",
        "sub","dl","dt","dd","abbr","small","mark","wbr","svg","path",
        "circle","rect","line","polyline","polygon",
      ],
      ALLOWED_ATTR: [
        "class","id","href","src","alt","title","target","rel","data-*",
        "style","width","height","viewBox","fill","stroke","stroke-width",
        "d","cx","cy","r","x","y","x1","y1","x2","y2","points","transform",
        "aria-*","role","type","value","placeholder","checked","disabled",
        "selected","for","name","required","min","max","step","pattern",
        "autocomplete","rows","cols","readonly","tabindex",
      ],
    });
  } else {
    element.textContent = html;
  }
};

window.safeSetHTML = N.Core.safeSetHTML;
})(window.Nous);
