/* =================================================================
   CHAT MARKDOWN — Safe markdown rendering & code block rendering
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
"use strict";

// ------------------------------------------------------------------
// Markdown code block rendering with syntax highlighting
// ------------------------------------------------------------------
function renderCodeBlock(lang, code) {
  const runnable = false;
  const escaped = esc(code);
  // Try highlight.js
  let highlighted = escaped;
  try {
    if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
      highlighted = hljs.highlight(code, { language: lang }).value;
    } else if (typeof hljs !== "undefined") {
      highlighted = hljs.highlightAuto(code).value;
    }
  } catch (_) {
    /* fallback to plain */
  }

  const uid = "codeblock-" + Math.random().toString(36).slice(2);
  // Build the wrapper HTML without inline onclick
  const wrapper = document.createElement("div");
  wrapper.className = "hljs-block-wrapper";
  wrapper.innerHTML =
    '<div class="hljs-block-header">' +
    '<span class="hljs-lang-badge">' +
    esc(lang || "") +
    "</span>" +
    '<div class="hljs-block-actions">' +
    '<button class="hljs-copy-btn"><i data-lucide="clipboard-list"></i> Copy</button>' +
    (runnable
      ? '<button class="hljs-run-btn"><i data-lucide="play"></i> Run</button>'
      : "") +
    "</div>" +
    "</div>" +
    '<pre style="margin:0;padding:8px 10px;background:#0d1117;overflow-x:auto;"><code class="hljs language-' +
    esc(lang || "") +
    '">' +
    highlighted +
    "</code></pre>" +
    '<div class="hljs-run-result" style="display:none;"></div>';

  // Attach event listeners via addEventListener (no inline onclick)
  const copyBtn = wrapper.querySelector(".hljs-copy-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      navigator.clipboard.writeText(code).then(function () {
        toast("コピーしました", "success");
      });
    });
  }
  if (runnable) {
    const runBtn = wrapper.querySelector(".hljs-run-btn");
    const resultEl = wrapper.querySelector(".hljs-run-result");
    if (runBtn && resultEl) {
      runBtn.addEventListener("click", function () {
        execCodeBlock(code, lang || "python", resultEl, runBtn);
      });
    }
  }

  return wrapper.outerHTML;
}

// ------------------------------------------------------------------
// Safe Markdown renderer using marked.js + DOMPurify
// ------------------------------------------------------------------
function safeMarkdown(text) {
  if (!text) return "";
  try {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      // Pre-process fenced code blocks to preserve onclick handlers through DOMPurify
      const codeBlocks = [];
      const textWithPlaceholders = text.replace(
        /```(\w*)\n([\s\S]*?)```/g,
        function (_, lang, code) {
          const idx = codeBlocks.length;
          codeBlocks.push(renderCodeBlock(lang || "", code.trimEnd()));
          return "CODEBLOCK_PLACEHOLDER_" + idx + "_END";
        },
      );
      const html = marked.parse(textWithPlaceholders, {
        breaks: true,
        gfm: true,
      });
      let sanitized = DOMPurify.sanitize(html, {
        ALLOWED_TAGS: [
          "p",
          "strong",
          "em",
          "b",
          "i",
          "u",
          "s",
          "code",
          "pre",
          "ul",
          "ol",
          "li",
          "h1",
          "h2",
          "h3",
          "h4",
          "blockquote",
          "a",
          "br",
          "hr",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
          "span",
          "img",
        ],
        ALLOWED_ATTR: [
          "href",
          "target",
          "rel",
          "title",
          "src",
          "alt",
          "width",
          "height",
        ],
      });
      // Restore code blocks (renderCodeBlock output is already escaped/safe)
      codeBlocks.forEach(function (block, idx) {
        sanitized = sanitized.replace(
          "CODEBLOCK_PLACEHOLDER_" + idx + "_END",
          block,
        );
      });
      return sanitized;
    }
  } catch (e) {
    /* fallback to escaped text */
  }
  return esc(text).replace(/\n/g, "<br>");
}

// ------------------------------------------------------------------
// Expose on N.Chat.markdown
// ------------------------------------------------------------------
N.Chat.markdown = {
  render: safeMarkdown,
  renderCode: renderCodeBlock,
};

// Also expose globally for other files that reference these directly:
window.safeMarkdown = safeMarkdown;
window.renderCodeBlock = renderCodeBlock;

})(window.Nous);
