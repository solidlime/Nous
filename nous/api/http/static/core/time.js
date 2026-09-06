/* =================================================================
   TIME HELPERS
   ================================================================= */
;(function(N) {

N.Core.relativeTime = function relativeTime(iso) {
  if (!iso) return "--";
  var diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  if (diff < 60000) return Math.floor(diff / 1000) + "s ago";
  if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
  if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
  return Math.floor(diff / 86400000) + "d ago";
};

N.Core.fmtDate = function fmtDate(iso) {
  if (!iso) return "--";
  return new Date(iso).toLocaleDateString("ja-JP", {
    month: "short", day: "numeric",
  });
};

N.Core.fmtDateTime = function fmtDateTime(iso) {
  if (!iso) return "--";
  return new Date(iso).toLocaleString("ja-JP");
};

})(window.Nous);
