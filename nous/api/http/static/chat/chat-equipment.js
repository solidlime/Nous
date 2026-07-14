;/* =================================================================
   CHAT EQUIPMENT — Equipment/inventory loading + rendering
   Extracted from chat-core.js + chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";

var CHAT = N.Chat.state;

/* ---- from chat-core.js ---- */
async function loadEquipment() {
  if (!S.persona) return;
  try {
    const data = await api("/api/dashboard/" + encodeURIComponent(S.persona));
    const equipment = data.equipment || {};
    updateEquipmentPanel({ equip: equipment });
  } catch (e) {
    console.error("[loadEquipment] failed:", e);
    toast("装備データ読込失敗: " + e.message, "error");
  }
}

/* ---- from chat.js ---- */
function updateEquipmentPanel(update) {
  const list = document.getElementById("memory-equipment-list");
  if (!list) return;
  if (!update) return;

  // Build equipment display from update data
  const equipped = update.equip || {};
  const unequipped = update.unequip || [];
  const added = update.add_items || [];

  let html = "";
  const entries = Object.entries(equipped).filter(function (e) {
    return e[1] != null && e[1] !== "";
  });
  if (entries.length > 0) {
    html +=
      '<div style="font-size:0.75rem;font-weight:600;color:var(--text-muted);margin-bottom:4px;"><i data-lucide="shield" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>装備中</div>';
    for (const [slot, item] of entries) {
      const slotIcon =
        {
          top: "shirt",
          bottom: "footprints",
          shoes: "footprints",
          outer: "jacket",
          accessories: "gem",
          head: "crown",
        }[slot] || "circle";
      const slotLabel =
        {
          top: "上",
          bottom: "下",
          shoes: "靴",
          outer: "アウター",
          accessories: "アクセ",
          head: "頭",
        }[slot] || slot;
      html +=
        '<div style="font-size:0.73rem;padding:2px 0;display:flex;justify-content:space-between;align-items:center;">' +
        '<span style="display:inline-flex;align-items:center;gap:4px;"><i data-lucide="' +
        slotIcon +
        '" style="width:11px;height:11px;opacity:0.7;"></i>' +
        slotLabel +
        "</span><span>" +
        esc(String(item)) +
        "</span></div>";
    }
  }
  if (unequipped.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:4px;">外した: ' +
      unequipped
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }
  if (added.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:2px;">追加: ' +
      added
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }

  if (html) {
    list.innerHTML = html;
    // Re-render Lucide icons in the equipment panel
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 10);
  }
}

N.Chat.equipment = {
  load: loadEquipment,
  update: updateEquipmentPanel,
};

window.loadEquipment = loadEquipment;
window.updateEquipmentPanel = updateEquipmentPanel;

})(window.Nous);
