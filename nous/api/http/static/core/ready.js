/* =================================================================
   LAZY BOOTSTRAP — whenReady / per-tab script loading (v4)
   shell.js is the only script in <head>; every tab's sources are
   listed in the head manifest (base.py LAZY_MANIFEST, SSOT) and
   fetched on first visit.
   ================================================================= */
;(function (N) {
"use strict";
var C = N.Core;

/* Tab sources load after first paint, when DOMContentLoaded has usually
   already fired — a plain listener would never run (settings-core.js:62,
   projects.js:130, timeline.js:163, wiki.js:493 all init that way). */
C.whenReady = function whenReady(fn) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  } else {
    fn();
  }
};

function manifest() {
  if (C._manifest === undefined) {
    C._manifest = null;
    var el = document.getElementById("lazy-manifest");
    if (el) {
      try { C._manifest = JSON.parse(el.textContent); }
      catch (e) { console.warn("[shell] bad lazy-manifest:", e); }
    }
  }
  return C._manifest;
}

function resolvePath(path) {
  var obj = window;
  var parts = String(path).split(".");
  for (var i = 0; i < parts.length; i++) {
    obj = obj[parts[i]];
    if (!obj) return null;
  }
  return typeof obj === "function" ? obj : null;
}

var _scripts = {};
/* One script tag, memoized per URL. onerror resolves too: a blocked CDN must
   not wedge the tab (the consumers guard their globals). */
C.loadScript = function loadScript(src) {
  if (_scripts[src]) return _scripts[src];
  _scripts[src] = new Promise(function (resolve) {
    var s = document.createElement("script");
    s.src = src;
    s.async = false;
    s.onload = s.onerror = function () { resolve(); };
    document.head.appendChild(s);
  });
  return _scripts[src];
};

C.loadDep = function loadDep(name) {
  var m = manifest();
  var url = m && m.deps && m.deps[name];
  if (!url) return Promise.resolve();
  /* vis-timeline-css: <link> で読む。createElement("script") では CSS が
     適用されない（v4 drive-by: Timeline の見た目が壊れる）。 */
  if (/\.css(\?|#|$)/.test(url)) {
    if (document.querySelector('link[href="' + url + '"]')) return Promise.resolve();
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = url;
    document.head.appendChild(link);
    return Promise.resolve();
  }
  return C.loadScript(url);
};

var _tabs = {};
/* Load a tab's sources (shared cores first, then the tab's own files, in
   manifest order) and resolve once its loader function is callable. */
C.loadTabScripts = function loadTabScripts(tab) {
  var m = manifest();
  var spec = m && m.tabs && m.tabs[tab];
  if (!spec) return Promise.resolve(false);
  if (_tabs[tab]) return _tabs[tab];
  var deps = Array.from(new Set((m.base || []).concat(spec.deps || [])));
  var srcs = (m.shared || []).concat(spec.scripts || []);
  _tabs[tab] = Promise.all(deps.map(C.loadDep))
    .then(function () {
      return srcs.reduce(function (p, src) {
        return p.then(function () { return C.loadScript(src); });
      }, Promise.resolve());
    })
    .then(function () {
      /* chat's entry is itself a loader — wait for what it booted. */
      var boot = spec.ready ? resolvePath(spec.ready) : null;
      return boot ? boot() : null;
    })
    .then(function () {
      C.refreshIcons();
      return true;
    })
    .catch(function (e) {
      console.warn("[shell] tab sources failed:", tab, e);
      delete _tabs[tab]; /* let the next tab switch retry */
      return false;
    });
  return _tabs[tab];
};

/* Tab CSS must not block first paint: attach it once the shell is up. */
C.whenReady(function () {
  var m = manifest();
  if (!m || !m.css || document.querySelector('link[href="' + m.css + '"]')) return;
  var link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = m.css;
  document.head.appendChild(link);
});
})(window.Nous);
