/* =================================================================
   OVERVIEW CHUNK — v4 第1段階（結合のみ・書き直しなし）
   A の manifest（sections/base.py LAZY_MANIFEST.tabs.overview）が
   scripts をこの 1 本に差し替え、ready: "Nous.Features.Overview.chunk.load" で呼ぶ想定の
   エントリ。中身は現行 manifest と同一の依存順で既存 IIFE を読み込む
   だけで、タブ本体は書き直していない。第2段階で manifest 側が SSOT に
   なり、この SCRIPTS 配列は消える。
   ================================================================= */
;(function (N) {
  "use strict";

  // 依存順 = sections/base.py LAZY_MANIFEST.tabs.overview.scripts と同一。
  var SCRIPTS = [
    "/static/features/overview/overview-blocks.js",
    "/static/features/overview/overview-inventory.js",
    "/static/features/overview/overview-core.js",
    "/static/features/overview/overview-stats.js",
    "/static/features/overview/overview-charts.js",
    "/static/features/overview/overview-context.js",
  ];

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = false;
      s.onload = function () { resolve(src); };
      s.onerror = function () { reject(new Error("overview chunk: failed to load " + src)); };
      document.head.appendChild(s);
    });
  }

  // 直列 await。async=false の挿入順保証は同一バッチ限りなので、
  // 順序が契約（N.Features.* の後勝ち定義）である以上 await する。
  function loadAll(list) {
    return list.reduce(function (p, src) {
      return p.then(function () { return loadScript(src); });
    }, Promise.resolve());
  }

  var booting = null;
  function loadOverviewChunk() {
    if (!booting) {
      booting = loadAll(SCRIPTS).then(function () {
        return N.Core.refreshIcons();
      });
      // 失敗したら次回のタブ要求で再試行できるようにする
      booting.catch(function () { booting = null; });
    }
    return booting;
  }

  N.Features = N.Features || {};
  N.Features.Overview = N.Features.Overview || {};
  N.Features.Overview.chunk = { scripts: SCRIPTS, load: loadOverviewChunk };
})(window.Nous = window.Nous || {});
