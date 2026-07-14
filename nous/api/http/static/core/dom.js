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

})(window.Nous);
