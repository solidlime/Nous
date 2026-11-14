/* =================================================================
   AUTH — API キーの自動付与（dashboard が 401 で全滅しないため）
   - fetch はグローバルに 1 回だけ包む（個々の呼び出し元を触らない）
   - EventSource はヘッダを送れないので SSE は ?token= を使う
   キーの出所は localStorage → ページ URL の ?token= の順。
   ================================================================= */
;(function(N) {
"use strict";

var KEY = "nousApiKey";

function _fromLocation() {
  try {
    var m = /[?&]token=([^&#]+)/.exec((window.location && window.location.search) || "");
    if (m) return decodeURIComponent(m[1]).trim();
  } catch (_) {}
  return "";
}

/* ?token= は保存したら URL から外す（履歴・ブックマーク・Referer に残さない）。 */
function _stripTokenFromUrl() {
  try {
    if (typeof history === "undefined" || !history.replaceState) return;
    var u = new URL(window.location.href);
    if (!u.searchParams.has("token")) return;
    u.searchParams.delete("token");
    history.replaceState(history.state, "", u.pathname + (u.search || "") + (u.hash || ""));
  } catch (_) {}
}

function _sameOrigin(url) {
  try {
    return new URL(url, window.location.href).origin === window.location.origin;
  } catch (_) {
    return true;
  }
}

N.Core.auth = {
  /* 保存済みキー。無ければ URL の ?token= を拾って保存する。 */
  token: function() {
    var t = "";
    try { t = (window.localStorage.getItem(KEY) || "").trim(); } catch (_) {}
    if (t) return t;
    t = _fromLocation();
    /* 保存できなかったら URL は消さない（そこが唯一のキーの所在になる）。 */
    if (t && this.store(t)) _stripTokenFromUrl();
    return t;
  },

  store: function(t) {
    try { window.localStorage.setItem(KEY, t); return true; } catch (_) { return false; }
  },

  clear: function() {
    try { window.localStorage.removeItem(KEY); } catch (_) {}
  },

  /* 既存ヘッダ（plain object / Headers / 配列）を壊さず Authorization を足す。
     instanceof Headers は realm を跨ぐと落ちるので、形で判定する。 */
  headers: function(h) {
    var t = this.token();
    if (!t) return h || {};
    var value = "Bearer " + t;
    var isHeaders = h && typeof h.get === "function" && typeof h.set === "function" &&
      typeof h.has === "function";
    if (isHeaders) {
      if (h.has("authorization")) return h;
      var copy = new Headers(h);
      copy.set("Authorization", value);
      return copy;
    }
    if (Array.isArray(h)) {
      var hasAuth = h.some(function(pair) {
        return String(pair && pair[0]).toLowerCase() === "authorization";
      });
      return hasAuth ? h : h.concat([["Authorization", value]]);
    }
    var out = Object.assign({}, h || {});
    var hasAuth = Object.keys(out).some(function(k) {
      return String(k).toLowerCase() === "authorization";
    });
    if (!hasAuth) out.Authorization = value;
    return out;
  },

  /* EventSource 用: URL に token= を足す（既にあれば触らない）。
     ヘッダを送れない代償としてキーが URL に乗る（アクセスログに残る）。
     恒久解は cookie セッション。 */
  sign: function(url) {
    var t = this.token();
    if (!t || !url || /[?&]token=/.test(url)) return url;
    if (!_sameOrigin(url)) return url;
    return url + (url.indexOf("?") === -1 ? "?" : "&") + "token=" + encodeURIComponent(t);
  }
};

/* ── fetch のグローバル包装 ──
   ダッシュボードの fetch は core/api.js 経由と生 fetch が混在していて、
   認証ヘッダを足す場所を個別に直すと必ず漏れる。
   代償: ここが壊れると全 API が同時に死ぬ。触るときは必ず実ブラウザで確かめる。 */
if (!window.fetch || !window.fetch._nousAuthWrapped) {
  var _origFetch = window.fetch;
  var _wrappedFetch = function(input, init) {
    init = init || {};
    var url = typeof input === "string" ? input : (input && input.url) || "";
    if (_sameOrigin(url)) {
      /* init.headers を渡すと Request 側のヘッダは置換される。Request を渡された
         場合はそのヘッダを土台にして足す（GLTFLoader の setRequestHeader 対策）。 */
      var base = init.headers;
      /* Realm を跨ぐと instanceof が落ちるので、headers を持つ入力なら土台にする。 */
      if (base === undefined && input && typeof input !== "string" && input.headers) {
        base = input.headers;
      }
      init.headers = N.Core.auth.headers(base);
    }
    return _origFetch.call(window, input, init).then(function(res) {
      /* 鍵がローテートされた場合、間違った鍵を送り続けない（次の ?token= で復帰）。 */
      if (res && res.status === 401 && N.Core.auth.token()) N.Core.auth.clear();
      return res;
    });
  };
  _wrappedFetch._nousAuthWrapped = true;
  window.fetch = _wrappedFetch;
}

})(window.Nous);
