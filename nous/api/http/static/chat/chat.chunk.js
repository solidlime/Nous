/* =================================================================
   CHAT CHUNK — v4 第1段階（結合のみ・書き直しなし）
   shell.js が Chat タブ要求時に import('/static/chat/chat.chunk.js')
   するだけのエントリ。中身は sections/base.py と同一の依存順で既存
   IIFE を読み込む。第2段階で A の manifest（base.py 定数）が SSOT に
   なり、この SCRIPTS 配列は消える。
   ================================================================= */
;(function (N) {
  "use strict";

  // 依存順 = 現行 base.py の <script> 順。facade（chat-send.js /
  // chat-history.js / chat-memory-panel.js / chat-settings.js）は
  // 実装が下位 sub-chunk 側にあるが、順序維持のためここに残す。
  var SCRIPTS = [
    "/static/chat/chat-core.js",
    "/static/chat/chat-settings.js",
    "/static/chat/settings/reset.js",
    "/static/chat/settings/apply.js",
    "/static/chat/settings/apply-groups.js",
    "/static/chat/settings/save.js",
    "/static/chat/chat-settings-mcp.js",
    "/static/chat/chat-settings-image.js",
    "/static/chat/chat-markdown.js",
    "/static/chat/chat-send.js",
    "/static/chat/send/render.js",
    "/static/chat/send/turn.js",
    "/static/chat/send/pending.js",
    "/static/chat/send/turn-events.js",
    "/static/chat/chat-history.js",
    "/static/chat/history/render.js",
    "/static/chat/history/session.js",
    "/static/chat/history/restore.js",
    "/static/chat/chat-memory-panel.js",
    "/static/chat/memory-panel/panel.js",
    "/static/chat/memory-panel/wiring.js",
    "/static/chat/memory-panel/wiring-stream.js",
    "/static/chat/memory-panel/wiring-detail.js",
    "/static/chat/memory-panel/detail.js",
    "/static/chat/chat-tools.js",
    "/static/chat/chat-equipment.js",
    "/static/chat/chat-commands.js",
    "/static/chat/chat-attachments.js",
    "/static/chat/chat-tts.js",
    "/static/chat/chat-tts-stream.js",
    "/static/chat/chat-voice.js",
  ];

  // three/VRM 依存は chunk 内で遅延 load（初期パスに載せない）。
  // ?v= は chat_layout_suffix の script タグと同一 URL にしないと
  // モジュール実体が二重になる。A が suffix のタグを外したら
  // バージョンはここだけが持つ。
  var AVATAR_MODULE = "/static/chat/avatar/chat-mode.js?v=20260914c";

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = false;
      s.onload = function () { resolve(src); };
      s.onerror = function () { reject(new Error("chat chunk: failed to load " + src)); };
      document.head.appendChild(s);
    });
  }

  // 直列 await。async=false の挿入順保証は同一バッチ限りなので、
  // 順序が契約（lucide ガード・N.Chat の後勝ち定義）である以上 await する。
  function loadAll(list) {
    return list.reduce(function (p, src) {
      return p.then(function () { return loadScript(src); });
    }, Promise.resolve());
  }

  // v4: chat inner (memory + main + sidebar) を script 実行より先に注入する。
  // 理由: chat 各 script は読み込み時に DOM へ bind する前提で、
  // 後からの innerHTML 注入では (1) #tab-chat が二重化して初回表示が
  // 空になる (2) bind 済み init が不在 DOM に終わって機能が死ぬ
  // (3) innerHTML では <script>/<link> が実行・適用されない。
  var _layoutDone = false;
  function ensureLayout() {
    if (_layoutDone) return Promise.resolve();
    _layoutDone = true;
    var persona = ((window.S && window.S.persona)
      || (window.Nous && window.Nous.State && window.Nous.State.persona)
      || "");
    var host = document.getElementById("chat-layout");
    if (!persona || !host || document.getElementById("chat-input")) return Promise.resolve();
    return fetch("/api/chat/" + encodeURIComponent(persona) + "/layout", { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("chat layout " + res.status);
        return res.text();
      })
      .then(function (html) {
        // trusted: same-origin のサーバ生成 markup（SSR shell と同一物）。
        host.innerHTML = html;
        ensureChatAssets();
      })
      .catch(function (err) {
        _layoutDone = false; // 次回のタブ要求で再試行できるようにする
        throw err;
      });
  }

  // suffix 由来の資産タグは innerHTML では適用されないため JS で読む。
  // chat-mode module は AVATAR_MODULE の import が同一実体を担う。
  var _assetsDone = false;
  function ensureChatAssets() {
    if (_assetsDone) return;
    _assetsDone = true;
    appendCssOnce("https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css");
    appendCssOnce("/static/chat/avatar/avatar.css");
    loadScript("https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js")
      .catch(function () { /* 素のコードブロックに落ちるだけ */ });
  }
  function appendCssOnce(href) {
    if (document.querySelector('link[rel="stylesheet"][href="' + href + '"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = href;
    document.head.appendChild(l);
  }

  var booting = null;
  function loadChatChunk() {
    if (!booting) {
      booting = ensureLayout().then(function () {
        return loadAll(SCRIPTS);
      }).then(function () {
        return import(AVATAR_MODULE);
      });
      // 失敗したら次回のタブ要求で再試行できるようにする
      booting.catch(function () { booting = null; });
    }
    return booting;
  }

  // shortcut: N.Core.whenReady は A の shell.js 着地後は常に存在する。
  // 未着地の並行作業中だけの互換経路（着地後は到達しない）。
  var whenReady = (N.Core && N.Core.whenReady) || function (fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  };

  N.Chat = N.Chat || {};
  N.Chat.chunk = { scripts: SCRIPTS, avatar: AVATAR_MODULE, load: loadChatChunk };

  whenReady(function () { loadChatChunk(); });
})(window.Nous = window.Nous || {});
