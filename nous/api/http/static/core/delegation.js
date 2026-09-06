/* =================================================================
   DELEGATION — CSP-safe receivers for server-rendered templates.
   sections/*.py must contain ZERO inline handlers (onclick/oninput/
   onchange/onload/onerror); every interactive element carries data-*
   attributes instead, routed here via document-level listeners
   (chat-memory-panel.js precedent: data-* + closest + addEventListener).
   Loaded LAST in render_head so window.Nous exists. Runtime N.*
   lookups only — no captured references (defer order independent).
   ================================================================= */
;(function() {
  if (typeof window === "undefined" || !window.Nous) return;
  var N = window.Nous;
  if (N.Core && N.Core._delegationBound) return; // single-bind (tests reload)
  if (N.Core) N.Core._delegationBound = true;

  function callChat(ns, fn, arg) {
    var obj = ns ? (N.Chat && N.Chat[ns]) : N.Chat;
    if (obj && typeof obj[fn] === "function") obj[fn](arg);
  }

  function callFeature(ns, fn, arg) {
    var obj = N.Features && N.Features[ns];
    if (obj && typeof obj[fn] === "function") obj[fn](arg);
  }

  // ------------------------------------------------------------------
  // Click routing: data-action="<verb>"
  // ------------------------------------------------------------------
  document.addEventListener("click", function(e) {
    var el = e.target && e.target.closest ? e.target.closest("[data-action]") : null;
    if (!el) {
      // Wiring rows: role="button" rows open the edge detail modal
      // (chat-memory-panel.js). Reached only when no [data-action]
      // element matched — the row's mem-open button returns first.
      var wiringRow = e.target && e.target.closest
        ? e.target.closest("[data-wiring-open]") : null;
      if (wiringRow) {
        callChat("memoryPanel", "openWiringDetail",
          wiringRow.getAttribute("data-wiring-open"));
      }
      return;
    }
    var action = el.getAttribute("data-action");
    switch (action) {
      // Chat shell (chat_layout.py)
      case "chat-toggle-settings":
        callChat("core", "toggleSettings");
        break;
      case "chat-toggle-memory":
        callChat("core", "toggleMemory");
        break;
      case "chat-cancel":
        callChat(null, "cancel");
        break;
      case "chat-attach":
        callChat("attachments", "trigger");
        break;
      case "chat-voice":
        callChat("voice", "toggle");
        break;
      case "chat-export":
        callChat("history", "export");
        break;
      case "chat-send":
        callChat(null, "send");
        break;
      case "chat-close-viewer":
        // Replaces inner onclick="event.stopPropagation()": clicks inside
        // the viewer content must not close the overlay.
        if (e.target && e.target.closest && e.target.closest("#media-viewer-inner")) return;
        callChat("attachments", "closeViewer");
        break;
      // Settings sidebar (chat_sidebar*.py)
      case "chat-save":
        callChat("settings", "save");
        break;
      case "chat-clear":
        callChat("history", "clear");
        break;
      case "chat-format-mcp":
        callChat("settings", "formatMcpJson");
        break;
      case "chat-test-image":
        callChat("settings", "testImageGen");
        break;
      case "chat-test-tts":
        callChat("tts", "test");
        break;
      case "chat-toggle-next":
        // Exact parity with the removed IIFE toggle: inline-style read.
        var sib = el.nextElementSibling;
        if (sib) sib.style.display = sib.style.display === "none" ? "" : "none";
        break;
      // Memories edit modal (memories.py)
      case "mem-edit-close":
        callFeature("Memories", "closeEditModal");
        break;
      case "mem-edit-backdrop":
        // Exact parity with if(event.target===this): backdrop-only click.
        if (e.target !== el) return;
        callFeature("Memories", "closeEditModal");
        break;
      case "mem-edit-save":
        callFeature("Memories", "saveMemory");
        break;
      // Feature tabs (timeline.py / activity.py / overview.py)
      case "tl-reload":
        callFeature("Timeline", "loadTimeline");
        break;
      case "act-refresh":
        callFeature("Activity", "loadActivity", true);
        break;
      // Chat memory panel — wiring feed (chat-memory-panel.js)
      case "wiring-close":
        callChat("memoryPanel", "closeWiringDetail");
        break;
      case "wiring-open-memory":
        // Open the memory itself in the unified mem modal. Return (not
        // break): the row beneath carries [data-wiring-open] and must
        // NOT also fire the edge detail modal.
        if (N.Components && N.Components.memModal) {
          N.Components.memModal.open(el.getAttribute("data-wiring-key"));
        }
        return;
      default:
        break;
    }
  });

  // ------------------------------------------------------------------
  // Slider mirrors: data-mirror="<targetId>" data-mirror-format="..."
  // ------------------------------------------------------------------
  var EFFORT_LABELS = ["low", "medium", "high", "max"];
  function formatMirrorValue(format, value) {
    if (format === "fixed2") return parseFloat(value).toFixed(2);
    if (format === "fixed1") return parseFloat(value).toFixed(1);
    if (format === "percent") return String(Math.round(Number(value) * 100)) + "%";
    if (format === "topP") {
      var v = parseFloat(value);
      return isNaN(v) ? "—" : v.toFixed(2);
    }
    if (format === "effort") return EFFORT_LABELS[parseInt(value, 10)];
    return value; // raw
  }
  document.addEventListener("input", function(e) {
    var el = e.target && e.target.closest ? e.target.closest("[data-mirror]") : null;
    if (!el) return;
    var target = document.getElementById(el.getAttribute("data-mirror"));
    if (!target) return;
    var suffix = el.getAttribute("data-mirror-suffix") || "";
    target.textContent = String(formatMirrorValue(el.getAttribute("data-mirror-format") || "raw", el.value)) + suffix;
  });

  // ------------------------------------------------------------------
  // Enable/display toggles: data-toggle-target + data-toggle-mode
  // ------------------------------------------------------------------
  document.addEventListener("change", function(e) {
    // Brain dedicated-LLM toggle: show/hide the dedicated fields
    // (B2 — checkbox, so routed on change not click).
    var brainTgl = e.target && e.target.closest
      ? e.target.closest('[data-action="brain-llm-toggle"]') : null;
    if (brainTgl) {
      var brainFields = document.getElementById("chat-brain-llm-fields");
      if (brainFields) {
        brainFields.classList.toggle("settings-body-hidden", !brainTgl.checked);
      }
      return;
    }
    var el = e.target && e.target.closest ? e.target.closest("[data-toggle-target]") : null;
    if (!el) return;
    var target = document.getElementById(el.getAttribute("data-toggle-target"));
    if (!target) return;
    var mode = el.getAttribute("data-toggle-mode") || "disabled";
    if (mode === "disabled") {
      target.disabled = !el.checked;
    } else if (mode === "display" && el.checked) {
      target.style.display = el.getAttribute("data-toggle-value") || "";
    }
  });

  // ------------------------------------------------------------------
  // Password forms: Enter must not submit/reload (sections wrap each
  // password input in <form data-password-form> to silence the
  // "[DOM] Password field is not contained in a form" warning).
  // ------------------------------------------------------------------
  document.addEventListener("submit", function(e) {
    var form = e.target && e.target.closest ? e.target.closest("[data-password-form]") : null;
    if (form) e.preventDefault();
  });

  // ------------------------------------------------------------------
  // Wiring detail keyboard: Escape closes the overlay, Enter/Space
  // activates role="button" rows (moved from chat-memory-panel.js).
  // ------------------------------------------------------------------
  document.addEventListener("keydown", function(e) {
    if (e.key !== "Escape" && e.key !== "Enter" && e.key !== " ") return;
    var overlay = document.getElementById("wiring-detail-overlay");
    var open = overlay && overlay.style.display !== "none";
    if (open && e.key === "Escape") {
      e.stopPropagation();
      callChat("memoryPanel", "closeWiringDetail");
      return;
    }
    if ((e.key === "Enter" || e.key === " ") && !open &&
        e.target && e.target.closest && e.target.closest("[data-wiring-open]") &&
        // A focused [data-action] control handles its own click natively.
        !e.target.closest("[data-action]")) {
      e.preventDefault();
      var row = e.target.closest("[data-wiring-open]");
      callChat("memoryPanel", "openWiringDetail", row.getAttribute("data-wiring-open"));
    }
  });

  // ------------------------------------------------------------------
  // Persona avatar fallback (replaces inline onload/onerror on
  // #chat-persona-avatar). Listeners cover later src swaps via SSE;
  // the init checks cover empty src + already-settled images.
  // ------------------------------------------------------------------
  function bindAvatar() {
    var avatar = document.getElementById("chat-persona-avatar");
    if (!avatar || avatar._avatarBound) return;
    avatar._avatarBound = true;
    avatar.addEventListener("load", function() { avatar.style.display = ""; });
    avatar.addEventListener("error", function() { avatar.style.display = "none"; });
    if (!avatar.getAttribute("src")) {
      avatar.style.display = "none";
    } else if (avatar.complete && avatar.naturalWidth === 0) {
      avatar.style.display = "none";
    }
  }
  bindAvatar();
})();
