/* =================================================================
   THEME TOGGLE
   ================================================================= */
;(function(N) {
"use strict";
var safeSetHTML = N.Core.safeSetHTML;

N.Core.applyTheme = function applyTheme() {
  var dark = localStorage.getItem("mmcp-dark") !== "false";
  document.documentElement.className = dark ? "dark" : "light";
  var toggleEl = document.getElementById("dark-toggle");
  if (toggleEl) {
    safeSetHTML(toggleEl, dark
      ? '<i data-lucide="moon"></i>'
      : '<i data-lucide="sun"></i>');
  }
  N.Core.refreshIcons();
};

N.Core.toggleTheme = function toggleTheme() {
  var isDark = document.documentElement.classList.contains("dark");
  localStorage.setItem("mmcp-dark", isDark ? "false" : "true");
  N.Core.applyTheme();
};

/* N.Components.theme alias */
N.Components.theme = {
  apply: N.Core.applyTheme,
  toggle: N.Core.toggleTheme,
};
})(window.Nous);
