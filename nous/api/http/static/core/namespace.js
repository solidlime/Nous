/* =================================================================
   NAMESPACE BOOTSTRAP
   Must load FIRST before any other Nous module.
   jsdom-safe: falls back to globalThis when window is absent (tests).
   ================================================================= */
(function(global) {
  global.Nous = global.Nous || {};
  global.Nous.Core = global.Nous.Core || {};
  global.Nous.Components = global.Nous.Components || {};
  global.Nous.Chat = global.Nous.Chat || {};
  global.Nous.Features = global.Nous.Features || {};
})(typeof window !== "undefined" ? window : globalThis);

// Global alias — required by all feature/chat modules that reference N at the top level
var N = (typeof window !== "undefined" ? window : globalThis).Nous;
