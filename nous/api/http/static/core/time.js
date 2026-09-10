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

// Fixed-width "YYYY/MM/DD HH:MM" (local) — chat time labels. Locale
// variants shift with the environment; chat labels must not.
N.Core.fmtStamp = function fmtStamp(iso) {
  if (!iso) return "";
  var d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  var p = function (n) { return n < 10 ? "0" + n : "" + n; };
  return (
    d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) +
    " " + p(d.getHours()) + ":" + p(d.getMinutes())
  );
};

})(window.Nous);
