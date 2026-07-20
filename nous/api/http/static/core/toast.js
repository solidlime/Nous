/* =================================================================
   TOAST NOTIFICATIONS
   ================================================================= */
;(function(N) {

function _ensureContainer() {
  var c = document.getElementById("toast-container");
  if (!c) {
    c = document.createElement("div");
    c.id = "toast-container";
    c.className = "toast-container";
    document.body.appendChild(c);
  }
  return c;
}

function _limitToasts(container, max) {
  var toasts = container.querySelectorAll(".toast");
  while (toasts.length > max) {
    toasts[0].remove();
    toasts = container.querySelectorAll(".toast");
  }
}

N.Core.toast = function toast(msg, type) {
  type = type || "info";
  var c = _ensureContainer();
  _limitToasts(c, 5);
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.textContent = msg;
  c.appendChild(t);
  t.addEventListener("animationend", function(e) {
    if (e.animationName !== "toastOut") return;
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  });
  setTimeout(function() {
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  }, 3200);
};

/* Toast with action button (e.g. retry) */
N.Core.toastAction = function toastAction(msg, type, actionLabel, actionFn) {
  type = type || "info";
  var c = _ensureContainer();
  _limitToasts(c, 5);
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
      if (t.dataset.removed) return;
      t.dataset.removed = "1";
      t.remove();
    };
    t.appendChild(btn);
  }
  c.appendChild(t);
  t.addEventListener("animationend", function(e) {
    if (e.animationName !== "toastOut") return;
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  });
  setTimeout(function() {
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  }, 5000);
};

window.toast = N.Core.toast;
})(window.Nous);
