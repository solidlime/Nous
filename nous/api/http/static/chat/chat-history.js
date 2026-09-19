/* =================================================================
   CHAT HISTORY — facade / split marker
   Implementation was split (1025 lines) into:
     history/render.js   — segment bubble renderer + shared renderer
     history/session.js  — welcome/reset, clear, rollback, edit, delete
     history/restore.js  — page-load restore, lazy-load, export
   See sections/base.py for the script-tag order. This file is kept
   as a thin forwarder so existing HTML script references keep
   working; it registers nothing.
   ================================================================= */
// (no-op) — all logic lives in history/*.js