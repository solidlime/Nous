/* =================================================================
   WIKI TAB — 記憶 wiki の閲覧（一覧 → 本文 → [[リンク]] 遷移）
   Namespace: N.Features.Wiki.*
   読み取り専用。編纂の起動は POST /api/wiki/run/{persona} だが
   plugin key が要るのでダッシュボードからは叩かない。
   ================================================================= */
N.Features.Wiki = N.Features.Wiki || {};

;(function() {
var S = window.S;
var { esc, api, safeSetHTML } = window.Nous.Core;

var WIKI = { pages: [], current: null, page: null, q: "", timer: null, revisions: [] };

var CATEGORY_ORDER = ["journal", "project", "persona", "other"];
var CATEGORY_LABELS = { journal: "日記", project: "プロジェクト", persona: "人柄", other: "その他" };

function persona() { return (S && S.persona) || ""; }

function listUrl(q) {
  var base = "/api/wiki/" + encodeURIComponent(persona());
  return q ? base + "?q=" + encodeURIComponent(q) : base;
}

function slugPath(slug) {
  return String(slug).split("/").map(encodeURIComponent).join("/");
}

function pageUrl(slug) {
  return listUrl() + "/" + slugPath(slug);
}

/* 予約パス（slug に使えない ``_`` 始まり）— 履歴 / 復元 / 手動編纂 */
function historyUrl(slug, rev) {
  return listUrl() + "/_history" + (rev ? "/" + rev : "") + "/" + slugPath(slug);
}

function restoreUrl(slug, rev) {
  return listUrl() + "/_restore/" + rev + "/" + slugPath(slug);
}

function recompileUrl() {
  return listUrl() + "/_recompile";
}

function notify(msg, kind) {
  var core = window.Nous && window.Nous.Core;
  if (core && typeof core.toast === "function") { core.toast(msg, kind || "info"); return; }
  console.info("[wiki]", msg);
}

/* -----------------------------------------------------------------
   一覧
   ----------------------------------------------------------------- */
function renderList() {
  const list = document.getElementById("wiki-list");
  if (!list) return;
  if (!WIKI.pages.length) {
    safeSetHTML(list,
      '<div style="padding:12px;font-size:0.85rem;color:var(--text-muted);">' +
      (WIKI.q ? "「" + esc(WIKI.q) + "」に一致するページは無い。" : "ページがまだない。編纂が走ると生まれる。") +
      "</div>");
    return;
  }
  const groups = {};
  for (const p of WIKI.pages) {
    const cat = p.category || "other";
    (groups[cat] = groups[cat] || []).push(p);
  }
  let html = "";
  for (const cat of CATEGORY_ORDER) {
    const items = groups[cat];
    if (!items) continue;
    html += '<details class="wiki-cat" open><summary>' + esc(CATEGORY_LABELS[cat] || cat) +
      ' <span class="wiki-cat-count">(' + items.length + ')</span></summary>';
    for (const p of items) {
      const nSrc = (p.sources || []).length;
      const active = WIKI.current === p.slug ? " active" : "";
      const hits = p.body_hits ? " · 本文" + p.body_hits + "行" : "";
      const proj = (cat === "project" && p.project) ? esc(p.project) + " · " : "";
      html +=
        '<button class="wiki-item' + active + '" data-wiki-slug="' + esc(p.slug) + '">' +
        '<span class="wiki-item-title">' + esc(p.title || p.slug) + "</span>" +
        '<span class="wiki-item-meta">' + proj + nSrc + " sources · " + esc((p.updated || "").slice(0, 10)) + hits + "</span>" +
        "</button>";
    }
    html += "</details>";
  }
  safeSetHTML(list, html);
  list.querySelectorAll("[data-wiki-slug]").forEach(function(btn) {
    btn.addEventListener("click", function() { loadPage(btn.getAttribute("data-wiki-slug")); });
  });
}

/* -----------------------------------------------------------------
   逆リンク / 検索一致の表示
   ----------------------------------------------------------------- */
function renderSub(page) {
  var el = document.getElementById("wiki-sub");
  if (!el) return;
  var parts = [];
  var back = page.backlinks || [];
  if (back.length) {
    parts.push("<span>被参照</span>");
    for (var i = 0; i < back.length; i++) {
      parts.push('<button class="wiki-chip" data-wiki-slug="' + esc(back[i]) + '">' + esc(back[i]) + "</button>");
    }
  }
  var matches = page.matches || [];
  if (matches.length) parts.push("<span>一致 " + matches.length + " 行（本文中を強調）</span>");
  var out = page.links || [];
  if (out.length) parts.push("<span>参照 " + out.length + " 件</span>");
  safeSetHTML(el, parts.join(""));
  el.querySelectorAll("[data-wiki-slug]").forEach(function(btn) {
    btn.addEventListener("click", function() { loadPage(btn.getAttribute("data-wiki-slug")); });
  });
}

/* 本文中の一致語を <mark> で強調する（DOM のテキストノードだけを触る）。 */
function highlightQuery(root, query) {
  if (!root || !query) return 0;
  var needle = String(query).toLowerCase();
  if (!needle.trim()) return 0;
  var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  var nodes = [];
  var node;
  while ((node = walker.nextNode())) {
    if (node.nodeValue && node.nodeValue.toLowerCase().indexOf(needle) !== -1) nodes.push(node);
  }
  var hits = 0;
  for (var n = 0; n < nodes.length; n++) {
    var text = nodes[n].nodeValue;
    var frag = document.createDocumentFragment();
    var at = 0;
    var idx = text.toLowerCase().indexOf(needle, at);
    while (idx !== -1) {
      if (idx > at) frag.appendChild(document.createTextNode(text.slice(at, idx)));
      var mark = document.createElement("mark");
      mark.className = "wiki-hit";
      mark.textContent = text.slice(idx, idx + needle.length);
      frag.appendChild(mark);
      hits++;
      at = idx + needle.length;
      idx = text.toLowerCase().indexOf(needle, at);
    }
    if (at < text.length) frag.appendChild(document.createTextNode(text.slice(at)));
    if (nodes[n].parentNode) nodes[n].parentNode.replaceChild(frag, nodes[n]);
  }
  return hits;
}

/* -----------------------------------------------------------------
   履歴 / 差分 / 復元
   ----------------------------------------------------------------- */
function diffLines(before, after) {
  var A = String(before || "").split("\n");
  var B = String(after || "").split("\n");
  var n = A.length, m = B.length;
  var dp = [];
  for (var i = 0; i <= n; i++) dp.push(new Array(m + 1).fill(0));
  for (i = n - 1; i >= 0; i--) {
    for (var j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  var rows = [];
  var a = 0, b = 0;
  while (a < n && b < m) {
    if (A[a] === B[b]) { rows.push({ t: " ", s: A[a] }); a++; b++; }
    else if (dp[a + 1][b] >= dp[a][b + 1]) { rows.push({ t: "-", s: A[a] }); a++; }
    else { rows.push({ t: "+", s: B[b] }); b++; }
  }
  while (a < n) rows.push({ t: "-", s: A[a++] });
  while (b < m) rows.push({ t: "+", s: B[b++] });
  return rows;
}

function closeHistory() {
  var el = document.getElementById("wiki-history");
  if (el) safeSetHTML(el, "");
}

function renderHistory(slug, revisions) {
  var el = document.getElementById("wiki-history");
  if (!el) return;
  if (!revisions.length) {
    safeSetHTML(el, '<div class="wiki-panel-head">履歴</div><div class="wiki-rev-meta">まだ履歴が無い（初回書き込みのみ）。</div>');
    return;
  }
  var html = '<div class="wiki-panel-head">履歴（新しい順・最大20版）</div>';
  for (var i = 0; i < revisions.length; i++) {
    var r = revisions[i];
    var label = (r.action === "delete" ? "削除" : "更新") + " · " + String(r.at || "").slice(0, 19).replace("T", " ");
    html += '<div class="wiki-rev"><span>rev ' + esc(String(r.rev)) + "</span>" +
      '<span class="wiki-rev-meta">' + esc(label) + " · " + esc(String(r.bytes)) + "B</span>" +
      '<button class="wiki-chip" data-wiki-diff="' + esc(String(r.rev)) + '">差分</button>' +
      '<button class="wiki-chip" data-wiki-restore="' + esc(String(r.rev)) + '">復元</button></div>';
  }
  safeSetHTML(el, html);
  el.querySelectorAll("[data-wiki-diff]").forEach(function(btn) {
    btn.addEventListener("click", function() { showRevision(slug, btn.getAttribute("data-wiki-diff")); });
  });
  el.querySelectorAll("[data-wiki-restore]").forEach(function(btn) {
    btn.addEventListener("click", function() { restoreRevision(slug, btn.getAttribute("data-wiki-restore")); });
  });
}

async function openHistory(slug) {
  var el = document.getElementById("wiki-history");
  var target = slug || (WIKI.page && WIKI.page.slug);
  if (!el || !target) return;
  safeSetHTML(el, '<div class="wiki-panel-head">履歴</div><div class="wiki-rev-meta">取得中…</div>');
  try {
    var data = await api(historyUrl(target));
    WIKI.revisions = (data && data.revisions) || [];
    renderHistory(target, WIKI.revisions);
  } catch (e) {
    safeSetHTML(el, '<div class="wiki-panel-head">履歴</div><div class="wiki-rev-meta">履歴を取得できない。</div>');
    console.warn("[wiki] history failed:", target, e);
  }
}

async function showRevision(slug, rev) {
  var el = document.getElementById("wiki-history");
  if (!el) return;
  try {
    var data = await api(historyUrl(slug, rev));
    var rows = diffLines(String(data.current_body || ""), String(data.body || ""));
    var html = '<div class="wiki-panel-head">rev ' + esc(String(rev)) + " との差分（現在 → この版）</div>";
    html += '<div class="wiki-diff">';
    for (var i = 0; i < rows.length; i++) {
      var cls = rows[i].t === "+" ? "add" : rows[i].t === "-" ? "del" : "";
      html += cls
        ? '<span class="' + cls + '">' + esc(rows[i].t + " " + rows[i].s) + "</span>\n"
        : esc("  " + rows[i].s) + "\n";
    }
    html += "</div>";
    html += '<div class="wiki-edit-actions"><button class="glass-btn" id="wiki-rev-restore">この版に戻す</button>' +
      '<button class="glass-btn" id="wiki-rev-close">閉じる</button></div>';
    safeSetHTML(el, html);
    var back = document.getElementById("wiki-rev-restore");
    if (back) back.addEventListener("click", function() { restoreRevision(slug, rev); });
    var close = document.getElementById("wiki-rev-close");
    if (close) close.addEventListener("click", function() { openHistory(slug); });
  } catch (e) {
    safeSetHTML(el, '<div class="wiki-panel-head">履歴</div><div class="wiki-rev-meta">この版を取得できない。</div>');
    console.warn("[wiki] revision failed:", slug, rev, e);
  }
}

async function restoreRevision(slug, rev) {
  if (!window.confirm("「" + slug + "」を rev " + rev + " に戻す？")) return;
  try {
    await api(restoreUrl(slug, rev), { method: "POST" });
    notify("rev " + rev + " に戻した", "success");
    closeHistory();
    await loadWiki();
    await loadPage(slug);
  } catch (e) {
    notify("復元できない: " + (e && e.message ? e.message : e), "error");
    console.warn("[wiki] restore failed:", slug, rev, e);
  }
}

/* 手動で編纂を 1 回走らせる（サーバー側は 202 で受付のみ・60 秒クールダウン）。 */
async function recompileWiki() {
  if (!persona()) return;
  var btn = document.getElementById("wiki-btn-recompile");
  if (btn) btn.disabled = true;
  try {
    await api(recompileUrl(), { method: "POST" });
    notify("編纂を受け付けた。反映まで数分かかる。", "success");
  } catch (e) {
    notify("編纂を起動できない: " + (e && e.message ? e.message : e), "error");
    console.warn("[wiki] recompile failed:", e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* -----------------------------------------------------------------
   本文（[[slug]] を内部リンクへ）
   ----------------------------------------------------------------- */
function toHtml(markdown) {
  const withLinks = String(markdown || "").replace(/\[\[([^\]\n]{1,120})\]\]/g, function(_, raw) {
    const slug = raw.trim();
    return "[" + slug + "](#wiki:" + encodeURIComponent(slug) + ")";
  });
  if (typeof marked === "undefined") return "<pre>" + esc(withLinks) + "</pre>";
  try { return marked.parse(withLinks, { mangle: false, headerIds: false }); }
  catch (_) { return "<pre>" + esc(withLinks) + "</pre>"; }
}

function renderPage(page) {
  const head = document.getElementById("wiki-article-head");
  const body = document.getElementById("wiki-article-body");
  if (!head || !body) return;
  const meta = [
    page.project ? "project: " + page.project : "",
    (page.sources || []).length + " sources",
    page.updated ? "updated " + String(page.updated).slice(0, 10) : "",
  ].filter(Boolean).join(" · ");
  safeSetHTML(head,
    '<h2 style="font-size:1.15rem;font-weight:700;color:var(--text-primary);">' + esc(page.title || page.slug) +
    "</h2>" +
    '<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">' + esc(meta) + "</div>");
  safeSetHTML(body, toHtml(page.body));
  highlightQuery(body, WIKI.q);
  renderSub(page);
  body.querySelectorAll('a[href^="#wiki:"]').forEach(function(a) {
    const slug = decodeURIComponent(a.getAttribute("href").slice("#wiki:".length));
    a.addEventListener("click", function(ev) {
      ev.preventDefault();
      loadPage(slug);
    });
  });
  if (typeof lucide !== "undefined") lucide.createIcons();
}

function renderEmpty() {
  const head = document.getElementById("wiki-article-head");
  const body = document.getElementById("wiki-article-body");
  if (head) safeSetHTML(head, "");
  closeHistory();
  var sub = document.getElementById("wiki-sub");
  if (sub) safeSetHTML(sub, "");
  if (body) safeSetHTML(body,
    '<div style="padding:24px;text-align:center;color:var(--text-muted);font-size:0.85rem;">' +
    "左の一覧からページを選ぶ。</div>");
}

/* -----------------------------------------------------------------
   取得
   ----------------------------------------------------------------- */
async function loadPage(slug) {
  if (!persona()) return;
  try {
    // 検索中は一致行も本文に重ねる（ハイライト用）。
    const page = await api(pageUrl(slug) + (WIKI.q ? "?q=" + encodeURIComponent(WIKI.q) : ""));
    WIKI.current = page.slug || slug;
    WIKI.page = page;
    renderPage(page);
    renderList();
  } catch (e) {
    closeHistory();
    const body = document.getElementById("wiki-article-body");
    if (body) safeSetHTML(body,
      '<div style="padding:24px;color:var(--text-muted);font-size:0.85rem;">' +
      "読み込めない: " + esc(slug) + "</div>");
    console.warn("[wiki] page load failed:", slug, e);
  }
}

async function loadWiki(q) {
  if (!persona()) return;
  if (q !== undefined) WIKI.q = q;
  try {
    const data = await api(listUrl(WIKI.q));
    WIKI.pages = (data && data.pages) || [];
    renderList();
    if (!WIKI.pages.length) { if (!WIKI.q) renderEmpty(); return; }
    const stillThere = WIKI.pages.some(function(p) { return p.slug === WIKI.current; });
    await loadPage(stillThere ? WIKI.current : WIKI.pages[0].slug);
  } catch (e) {
    const list = document.getElementById("wiki-list");
    if (list) safeSetHTML(list,
      '<div style="padding:12px;font-size:0.85rem;color:var(--text-muted);">' +
      "wiki を取得できない。</div>");
    console.warn("[wiki] list load failed:", e);
  }
}

/* -----------------------------------------------------------------
   編集（保存後のページは編纂の対象になる）
   ----------------------------------------------------------------- */
function enterEdit() {
  const page = WIKI.page;
  if (!page || !page.slug) return;
  const head = document.getElementById("wiki-article-head");
  const body = document.getElementById("wiki-article-body");
  if (!head || !body) return;

  const titleEl = document.createElement("input");
  titleEl.id = "wiki-edit-title";
  titleEl.value = page.title || page.slug;
  head.replaceChildren(titleEl);

  const textarea = document.createElement("textarea");
  textarea.id = "wiki-edit-body";
  textarea.value = page.body || "";

  const actions = document.createElement("div");
  actions.className = "wiki-edit-actions";
  const save = document.createElement("button");
  save.className = "glass-btn";
  save.id = "wiki-save";
  save.textContent = "保存";
  const cancel = document.createElement("button");
  cancel.className = "glass-btn";
  cancel.id = "wiki-cancel";
  cancel.textContent = "やめる";
  actions.append(save, cancel);

  body.replaceChildren(textarea, actions);
  save.addEventListener("click", function() { saveEdit(page.slug); });
  cancel.addEventListener("click", function() { renderPage(page); });
  textarea.focus();
}

async function saveEdit(slug) {
  const titleEl = document.getElementById("wiki-edit-title");
  const bodyEl = document.getElementById("wiki-edit-body");
  if (!bodyEl) return;
  const saveBtn = document.getElementById("wiki-save");
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "保存中…"; }
  try {
    await api(pageUrl(slug), {
      method: "PUT",
      body: JSON.stringify({
        title: titleEl ? titleEl.value : slug,
        body: bodyEl.value,
      }),
    });
    await loadWiki();
    await loadPage(slug);
  } catch (e) {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = "保存"; }
    const body = document.getElementById("wiki-article-body");
    if (body && body.querySelector("#wiki-edit-body")) return; // 編集中は潰さない
    renderPage(WIKI.page || { slug: slug, title: slug, body: "" });
    console.warn("[wiki] save failed:", e);
  }
}

/* -----------------------------------------------------------------
   削除（取り消せないので、必ず確認をとおす）
   ----------------------------------------------------------------- */
async function deletePage(slug) {
  if (!slug) return;
  if (!window.confirm("「" + slug + "」を削除する？ 元に戻せないよ。")) return;
  const btn = document.getElementById("wiki-btn-delete");
  if (btn) btn.disabled = true;
  try {
    await api(pageUrl(slug), { method: "DELETE" });
    WIKI.current = null;
    WIKI.page = null;
    renderEmpty();
    await loadWiki();
  } catch (e) {
    if (btn) btn.disabled = false;
    console.warn("[wiki] delete failed:", e);
  }
}

function refreshWiki() {
  const btn = document.getElementById("wiki-btn-refresh");
  if (btn) btn.addEventListener("click", function() { loadWiki(); });
  const edit = document.getElementById("wiki-btn-edit");
  if (edit) edit.addEventListener("click", enterEdit);
  const hist = document.getElementById("wiki-btn-history");
  if (hist) hist.addEventListener("click", function() {
    if (WIKI.page && WIKI.page.slug) openHistory(WIKI.page.slug);
  });
  const rerun = document.getElementById("wiki-btn-recompile");
  if (rerun) rerun.addEventListener("click", recompileWiki);
  const del = document.getElementById("wiki-btn-delete");
  if (del) del.addEventListener("click", function() {
    if (WIKI.page && WIKI.page.slug) deletePage(WIKI.page.slug);
  });
  const search = document.getElementById("wiki-search");
  if (search) search.addEventListener("input", function() {
    if (WIKI.timer) clearTimeout(WIKI.timer);
    // 1 文字ごとにサーバーを叩かない（本文 grep はファイル全体を読む）。
    WIKI.timer = setTimeout(function() { loadWiki(search.value.trim()); }, 250);
  });
}

N.Features.Wiki = {
  loadWiki: loadWiki,
  loadPage: loadPage,
  enterEdit: enterEdit,
  saveEdit: saveEdit,
  deletePage: deletePage,
  openHistory: openHistory,
  showRevision: showRevision,
  restoreRevision: restoreRevision,
  recompileWiki: recompileWiki,
  diffLines: diffLines,
  highlightQuery: highlightQuery,
  _state: WIKI,
};

document.addEventListener("DOMContentLoaded", refreshWiki);
})();
