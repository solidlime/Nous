/* =================================================================
   CHAT MARKDOWN — Safe markdown rendering & code block rendering
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";

// ------------------------------------------------------------------
// Custom marked renderer for GFM task lists
// marked v12 does not emit contains-task-list / task-list-item classes.
// Register once at module init (marked.use is global).
// ------------------------------------------------------------------
if (typeof marked !== "undefined" && marked.use) {
  marked.use({
    renderer: {
      checkbox: function (checked) {
        return '<input class="task-list-item-checkbox"' +
          (checked ? ' checked=""' : '') +
          ' disabled type="checkbox">';
      },
      listitem: function (text, task, checked) {
        return '<li' + (task ? ' class="task-list-item"' : '') + '>' +
          text + '</li>\n';
      },
    },
  });
}

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
  safeSetHTML(wrapper,
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
    '<div class="hljs-run-result" style="display:none;"></div>');

  // Attach event listeners via addEventListener (no inline onclick)
  const copyBtn = wrapper.querySelector(".hljs-copy-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(code).then(function () {
          toast("コピーしました", "success");
        }).catch(function () {
          _fallbackCopyMD(code);
        });
      } else {
        _fallbackCopyMD(code);
      }
    });
  }
  if (runnable) {
    const runBtn = wrapper.querySelector(".hljs-run-btn");
    const resultEl = wrapper.querySelector(".hljs-run-result");
    if (runBtn && resultEl) {
      runBtn.addEventListener("click", function () {
        N.Chat.tools.execCode(code, lang || "python", resultEl, runBtn);
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
        /```([\w+#-]*)\n([\s\S]*?)```/g,
        function (_, lang, code) {
          /* Fence-lang allowlist: word chars plus + # - (e.g. c++, c#, f#). Else plain. */
          var safeLang = /^[\w+#-]{0,32}$/.test(lang || "") ? lang : "";
          const idx = codeBlocks.length;
          codeBlocks.push(renderCodeBlock(safeLang || "", code.trimEnd()));
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
          "input",
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
          "type",
          "checked",
          "disabled",
          "class",
        ],
      });
      // Collapse newline text nodes between block elements. .chat-bubble uses
      // white-space: pre-wrap (needed for streaming plain-text bubbles), which
      // would otherwise render markdown's block-separating newlines as visible
      // line breaks and inflate paragraph/line spacing. Code blocks are still
      // placeholders here, so their inner newlines stay protected.
      sanitized = sanitized.replace(/>[ \t]*\n+[ \t]*</g, "><").replace(/\n\s*$/, "");
      // Restore code blocks (renderCodeBlock output is already escaped/safe)
      codeBlocks.forEach(function (block, idx) {
        sanitized = sanitized.replace(
          "CODEBLOCK_PLACEHOLDER_" + idx + "_END",
          block,
        );
      });
      // Post-process: add contains-task-list class to ul containing checkbox inputs
      // (marked renderer adds task-list-item to li, but cannot add class to ul itself)
      sanitized = sanitized.replace(
        /<ul>([\s\S]*?)<\/ul>/g,
        function (match, inner) {
          if (inner.indexOf('type="checkbox"') === -1) return match;
          return '<ul class="contains-task-list">' + inner + '</ul>';
        },
      );
      return sanitized;
    }
  } catch (e) {
    /* fallback to escaped text */
  }
  return esc(text).replace(/\n/g, "<br>");
}

// ------------------------------------------------------------------
// Copy fallback (non-secure contexts)
// ------------------------------------------------------------------
function _fallbackCopyMD(text) {
  var textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    document.execCommand("copy");
    toast("コピーしました", "success");
  } catch (e) {
    toast("コピーに失敗しました", "error");
  } finally {
    document.body.removeChild(textarea);
  }
}

// ------------------------------------------------------------------
// Expose on N.Chat.markdown
// ------------------------------------------------------------------
N.Chat.markdown = {
  render: safeMarkdown,
  renderCode: renderCodeBlock,
};

})(window.Nous);
