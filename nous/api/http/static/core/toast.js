/* =================================================================
   TOAST NOTIFICATIONS
   ================================================================= */
;(function(N) {

N.Core.toast = function toast(msg, type) {
  type = type || "info";
  var c = document.getElementById("toast-container");
  if (!c) return;
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(function() { t.remove(); }, 3200);
};

})(window.Nous);
