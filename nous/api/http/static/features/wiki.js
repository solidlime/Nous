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

var WIKI = { pages: [], current: null, page: null, q: "", timer: null };

var CATEGORY_ORDER = ["journal", "project", "persona", "other"];
var CATEGORY_LABELS = { journal: "日記", project: "プロジェクト", persona: "人柄", other: "その他" };

function persona() { return (S && S.persona) || ""; }

function listUrl(q) {
  var base = "/api/wiki/" + encodeURIComponent(persona());
  return q ? base + "?q=" + encodeURIComponent(q) : base;
}

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
    WIKI.page = page;
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
  _state: WIKI,
};

document.addEventListener("DOMContentLoaded", refreshWiki);
})();
