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

var WIKI = { pages: [], current: null };

function persona() { return (S && S.persona) || ""; }

function listUrl() { return "/api/wiki/" + encodeURIComponent(persona()); }

function pageUrl(slug) {
  return listUrl() + "/" + String(slug).split("/").map(encodeURIComponent).join("/");
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
      'ページがまだない。編纂が走ると生まれる。</div>');
    return;
  }
  let html = "";
  for (const p of WIKI.pages) {
    const nSrc = (p.sources || []).length;
    const active = WIKI.current === p.slug ? " active" : "";
    html +=
      '<button class="wiki-item' + active + '" data-wiki-slug="' + esc(p.slug) + '">' +
      '<span class="wiki-item-title">' + esc(p.title || p.slug) + "</span>" +
      '<span class="wiki-item-meta">' + nSrc + " sources · " + esc((p.updated || "").slice(0, 10)) + "</span>" +
      "</button>";
  }
  safeSetHTML(list, html);
  list.querySelectorAll("[data-wiki-slug]").forEach(function(btn) {
    btn.addEventListener("click", function() { loadPage(btn.getAttribute("data-wiki-slug")); });
  });
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
    '<h2 style="font-size:1.15rem;font-weight:700;color:var(--text-primary);">' + esc(page.title || page.slug) + "</h2>" +
    '<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">' + esc(meta) + "</div>");
  safeSetHTML(body, toHtml(page.body));
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
    const page = await api(pageUrl(slug));
    WIKI.current = page.slug || slug;
    renderPage(page);
    renderList();
  } catch (e) {
    const body = document.getElementById("wiki-article-body");
    if (body) safeSetHTML(body,
      '<div style="padding:24px;color:var(--text-muted);font-size:0.85rem;">' +
      "読み込めない: " + esc(slug) + "</div>");
    console.warn("[wiki] page load failed:", slug, e);
  }
}

async function loadWiki() {
  if (!persona()) return;
  try {
    const data = await api(listUrl());
    WIKI.pages = (data && data.pages) || [];
    renderList();
    if (!WIKI.pages.length) { renderEmpty(); return; }
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

function refreshWiki() {
  const btn = document.getElementById("wiki-btn-refresh");
  if (btn) btn.addEventListener("click", function() { loadWiki(); });
}

N.Features.Wiki = {
  loadWiki: loadWiki,
  loadPage: loadPage,
  _state: WIKI,
};

document.addEventListener("DOMContentLoaded", refreshWiki);
})();
