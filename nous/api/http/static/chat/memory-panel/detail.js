/* =================================================================
   CHAT MEMORY PANEL DETAIL — panel row → memory modal routing
   Chunk 5/5 of chat-memory-panel.js. Namespace:
   N.Chat.memoryPanel.openPanelDetail.
   Depends on: components/mem-modal.js (rows route through the
   unified memory modal).
   ================================================================= */
;(function(N) {
"use strict";

// ------------------------------------------------------------------
// Panel row click → unified mem modal. Retrieved/saved/reflection rows
// all carry memory semantics: complete key → open(key) (fresh fetch),
// partial data → openMemory(partial).
// ------------------------------------------------------------------
function _panelAttrs(card) {
  return {
    key: card.getAttribute("data-key") || "",
    content: card.getAttribute("data-content") || "",
    importance: parseFloat(card.getAttribute("data-importance")),
    tags: (card.getAttribute("data-tags") || "").split(",").filter(Boolean),
    created_at: card.getAttribute("data-created") || null,
  };
}

function openPanelDetail(card) {
  if (!card || !card.getAttribute) return;
  var kind = card.getAttribute("data-panel-kind");
  var item = _panelAttrs(card);
  if (!kind || kind === "memory" || kind === "reflection") {
    if (item.key) N.Components.memModal.open(item.key);
    else N.Components.memModal.openMemory({
      content: item.content,
      importance: isNaN(item.importance) ? 0.5 : item.importance,
      tags: item.tags,
    });
  }
}

// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 5/5 — panel detail routing)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  openPanelDetail: openPanelDetail,
});
})(window.Nous);
