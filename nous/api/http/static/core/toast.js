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
    c.setAttribute("role", "status");
    c.setAttribute("aria-live", "polite");
    c.setAttribute("aria-atomic", "true");
    document.body.appendChild(c);
  }
  return c;
}

function _getMaxToasts() {
  return window.matchMedia('(max-width: 767px)').matches ? 2 : 5;
}

function _limitToasts(container, max) {
  var toasts = container.querySelectorAll(".toast");
  while (toasts.length > max) {
    toasts[0].remove();
    toasts = container.querySelectorAll(".toast");
  }
}

/* Swipe-to-dismiss for mobile toasts */
function _enableSwipeDismiss(t) {
  var startX = 0, startY = 0, dist = 0, moved = false;
  t.addEventListener("touchstart", function(e) {
    var touch = e.touches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    dist = 0;
    moved = false;
    t.style.transition = "none";
  }, {passive: true});
  t.addEventListener("touchmove", function(e) {
    var touch = e.touches[0];
    dist = touch.clientX - startX;
    var dy = Math.abs(touch.clientY - startY);
    if (dy > Math.abs(dist) * 1.5) return; // vertical scroll, not swipe
    if (Math.abs(dist) > 10) {
      moved = true;
      t.style.transform = "translateX(" + dist + "px)";
      t.style.opacity = Math.max(0, 1 - Math.abs(dist) / 150);
    }
  }, {passive: true});
  t.addEventListener("touchend", function(e) {
    t.style.transition = "";
    t.style.transform = "";
    t.style.opacity = "";
    if (moved && Math.abs(dist) > 80) {
      if (t.dataset.removed) return;
      t.dataset.removed = "1";
      t.style.transition = "transform 0.2s ease, opacity 0.2s ease";
      t.style.transform = "translateX(" + (dist > 0 ? 100 : -100) + "%)";
      t.style.opacity = "0";
      setTimeout(function() { t.remove(); }, 200);
    }
  }, {passive: true});
}

function _attachToast(t) {
  _enableSwipeDismiss(t);
  t.addEventListener("animationend", function _onAnimEnd(e) {
    if (e.animationName !== "toastOut") return;
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  });
}

function _autoRemove(t, delay) {
  setTimeout(function() {
    if (t.dataset.removed) return;
    t.dataset.removed = "1";
    t.remove();
  }, delay);
}

N.Core.toast = function toast(msg, type) {
  type = type || "info";
  var c = _ensureContainer();
  _limitToasts(c, _getMaxToasts());
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.setAttribute("role", "status");
  t.textContent = msg;
  c.appendChild(t);
  _attachToast(t);
  _autoRemove(t, 3200);
};

/* Toast with action button (e.g. retry) */
N.Core.toastAction = function toastAction(msg, type, actionLabel, actionFn) {
  type = type || "info";
  var c = _ensureContainer();
  _limitToasts(c, _getMaxToasts());
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.setAttribute("role", "status");
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
  _attachToast(t);
  _autoRemove(t, 5000);
};

/* N.Components.toast alias */
N.Components.toast = {
  show: N.Core.toast,
  info: function(msg) { N.Core.toast(msg, "info"); },
  success: function(msg) { N.Core.toast(msg, "success"); },
  error: function(msg) { N.Core.toast(msg, "error"); },
  warning: function(msg) { N.Core.toast(msg, "warning"); },
  action: N.Core.toastAction,
};
})(window.Nous);
