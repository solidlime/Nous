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
})(window.Nous);
