/* =================================================================
   CHAT MEMORY PANEL — facade / split marker
   Implementation was split (1133 lines) into:
     memory-panel/panel.js         — panel CRUD, reflection, delegation
     memory-panel/wiring.js        — synapse fire feed + fire-limit
     memory-panel/wiring-stream.js — wiring SSE connect/persona/visibility
     memory-panel/wiring-detail.js — fire detail modal viewer
     memory-panel/detail.js        — goal/promise panel detail modal
   See sections/base.py for the script-tag order. This file is kept
   as a thin forwarder so existing HTML script references keep
   working; it registers nothing.
   ================================================================= */
// (no-op) — all logic lives in memory-panel/*.js