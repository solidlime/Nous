/* =================================================================
   NAMESPACE BOOTSTRAP
   Must load FIRST before any other Nous module.
   ================================================================= */
(function(global) {
  global.Nous = global.Nous || {};
  global.Nous.Core = global.Nous.Core || {};
  global.Nous.Components = global.Nous.Components || {};
  global.Nous.Chat = global.Nous.Chat || {};
  global.Nous.Features = global.Nous.Features || {};
})(window);

// Global alias — required by all feature/chat modules that reference N at the top level
var N = window.Nous;
