/* =================================================================
   CHAT SETTINGS — facade / split marker
   Implementation was split (1438 lines) into:
     settings/reset.js        — defaults API + per-field reset
     settings/apply.js        — config loading + applyChatConfig core
     settings/apply-groups.js — voice/image/brain field groups
     settings/save.js         — saveChatConfig collection + POST
   See sections/base.py for the script-tag order. This file is kept
   as a thin forwarder so existing HTML script references keep
   working; it registers nothing.
   ================================================================= */
// (no-op) — all logic lives in settings/*.js