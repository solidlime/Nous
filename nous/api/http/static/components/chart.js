/* =================================================================
   CHART HELPERS COMPONENT — N.Components.chart
   ================================================================= */
;(function(N) {
"use strict";

/* ── Destroy a chart instance safely ── */
function destroy(idOrChart) {
  if (!idOrChart) return;
  /* Support both S.charts[id] references and Chart.js instance directly */
  var chart = typeof idOrChart === "string" ? (S && S.charts && S.charts[idOrChart]) : idOrChart;
  if (chart && typeof chart.destroy === "function") {
    chart.destroy();
  }
  if (typeof idOrChart === "string" && S && S.charts) {
    delete S.charts[idOrChart];
  }
}

/* ── Chart.js common options ── */
function defaults(extra) {
  extra = extra || {};
  var color =
    (typeof getComputedStyle !== "undefined"
      ? getComputedStyle(document.documentElement)
          .getPropertyValue("--text-muted")
          .trim()
      : null) || "#94a3b8";
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: color, font: { size: 11 } } },
      ...extra.plugins,
    },
    scales: extra.scales
      ? Object.fromEntries(
          Object.entries(extra.scales).map(function(kv) {
            var k = kv[0], v = kv[1];
            return [
              k,
              {
                ...v,
                ticks: { color: color, ...(v.ticks || {}) },
                grid: { color: "rgba(0,122,255,0.08)", ...(v.grid || {}) },
              },
            ];
          }),
        )
      : undefined,
  };
}

/* ── Export ── */
N.Components.chart = {
  destroy: destroy,
  defaults: defaults,
};

/* Reference for backward compatibility through S */
})(window.Nous);
