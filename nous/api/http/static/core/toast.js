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

/* Toast with action button (e.g. retry) */
N.Core.toastAction = function toastAction(msg, type, actionLabel, actionFn) {
  type = type || "info";
  var c = document.getElementById("toast-container");
  if (!c) return;
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.style.display = "flex";
  t.style.alignItems = "center";
  t.style.gap = "10px";
  var msgSpan = document.createElement("span");
  msgSpan.textContent = msg;
  msgSpan.style.flex = "1";
  t.appendChild(msgSpan);
  if (actionLabel && actionFn) {
    var btn = document.createElement("button");
    btn.textContent = actionLabel;
    btn.className = "toast-action-btn";
    btn.onclick = function() {
      actionFn();
      t.remove();
    };
    t.appendChild(btn);
  }
  c.appendChild(t);
  setTimeout(function() { t.remove(); }, 5000);
};

window.toast = N.Core.toast;
})(window.Nous);
