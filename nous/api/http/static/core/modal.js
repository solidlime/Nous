/* =================================================================
   CONFIRM / ALERT MODALS
   ================================================================= */
;(function(N) {
"use strict";

N.Core.showConfirm = function showConfirm(message, onConfirm, onCancel) {
  // Promise-based: showConfirm(msg) returns Promise<boolean>
  if (typeof onConfirm !== "function") {
    return new Promise(function(resolve) {
      N.Core.showConfirm(message, function() { resolve(true); }, function() { resolve(false); });
    });
  }
  var triggerEl = document.activeElement;
  var overlay = document.createElement("div");
  overlay.className = "confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML =
    '<div class="confirm-modal">' +
    '<h3 id="confirm-title">確認</h3>' +
    "<p>" +
    N.Core.esc(message).replace(/\n/g, "<br>") +
    "</p>" +
    '<div class="confirm-modal-actions">' +
    '<button class="glass-btn" id="confirm-cancel-btn">キャンセル</button>' +
    '<button class="glass-btn glass-btn-danger" id="confirm-ok-btn">OK</button>' +
    "</div></div>";
  overlay.setAttribute("aria-labelledby", "confirm-title");
  document.body.appendChild(overlay);
  requestAnimationFrame(function() { overlay.classList.add("show"); });

  var okBtn = document.getElementById("confirm-ok-btn");
  if (okBtn) okBtn.focus();

  function cleanup() {
    overlay.classList.remove("show");
    setTimeout(function() { overlay.remove(); }, 220);
    if (triggerEl && triggerEl.focus) triggerEl.focus();
  }
  okBtn.onclick = function() {
    cleanup();
    if (onConfirm) onConfirm();
  };
  document.getElementById("confirm-cancel-btn").onclick = function() {
    cleanup();
    if (onCancel) onCancel();
  };
  overlay.addEventListener("click", function(e) {
    if (e.target === overlay) { cleanup(); if (onCancel) onCancel(); }
  });
  overlay.addEventListener("keydown", function(e) {
    if (e.key === "Escape") { e.stopPropagation(); cleanup(); if (onCancel) onCancel(); return; }
    if (e.key === "Tab") {
      var focusable = overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusable.length === 0) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
};

N.Core.showAlert = function showAlert(message) {
  var triggerEl = document.activeElement;
  var overlay = document.createElement("div");
  overlay.className = "confirm-overlay";
  overlay.setAttribute("role", "alertdialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML =
    '<div class="confirm-modal">' +
    '<h3 id="alert-title">通知</h3>' +
    "<p>" +
    N.Core.esc(message).replace(/\n/g, "<br>") +
    "</p>" +
    '<div class="confirm-modal-actions">' +
    '<button class="glass-btn glass-btn-success" id="alert-ok-btn">OK</button>' +
    "</div></div>";
  overlay.setAttribute("aria-labelledby", "alert-title");
  document.body.appendChild(overlay);
  requestAnimationFrame(function() { overlay.classList.add("show"); });
  var okBtn = document.getElementById("alert-ok-btn");
  if (okBtn) okBtn.focus();
  function cleanup() {
    overlay.classList.remove("show");
    setTimeout(function() { overlay.remove(); }, 220);
    if (triggerEl && triggerEl.focus) triggerEl.focus();
  }
  okBtn.onclick = cleanup;
  overlay.addEventListener("click", function(e) { if (e.target === overlay) cleanup(); });
  overlay.addEventListener("keydown", function(e) {
    if (e.key === "Escape") { e.stopPropagation(); cleanup(); }
    if (e.key === "Tab") { e.preventDefault(); okBtn.focus(); }
  });
};

})(window.Nous);
