/* =================================================================
   CHAT SEND — facade / split marker
   Implementation was split (1242 lines) into:
     send/render.js       — message DOM rendering, typing, scroll, clipboard
     send/pending.js      — send payload build, pending queue, cancel
     send/turn.js         — turn hub engine + chat-events SSE
     send/turn-events.js  — per-event streaming renderer + finalize
     send/monologue.js    — REM monologue display-only whispers
   See sections/base.py for the script-tag order. This file is kept
   as a thin forwarder so existing HTML script references keep
   working; it registers nothing.
   ================================================================= */
// (no-op) — all logic lives in send/*.js