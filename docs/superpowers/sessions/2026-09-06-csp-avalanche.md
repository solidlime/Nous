# Session record — 2026-09-06 CSP avalanche (WebUI browser-error sweep)

## Goal evolution
Bug-fix-all (pushed through e71597d6) → brain-wiring F1–F5 + firing feed (pushed) →
user local-verify → server restart → user reported "browser full of errors" →
root-cause: our own CSP header → fix + re-verify. Permit: record-to-file
(memory API absent this session; durable fallback).

## Root cause (single)
`nous/api/http/middleware.py:40` served minimal
`default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'`,
diverging from oracle Q3 full-policy contract. Real-browser console: all 10 CDN
externals blocked (tailwind/jsdelivr×3/unpkg×3/cdnjs/fonts×2), hundreds of
runtime inline-style applications blocked, one inline handler blocked,
`data:audio/wav` TTS blocked. Cascade: `lucide is not defined` (dom.js:22),
unstyled page, dead TTS, `buildHamburgerMenu` null (base.js:318),
`_appendSegmentsToBubble` null (chat-history.js:132), favicon 404.

## Oracle re-ruling (ora-1, BLOCK on minimal, exact replacement)
`default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com; img-src 'self' data: blob:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; media-src 'self' data: blob:`
Keep: COOP same-origin, XFO DENY, object-src none, HSTS https-only.
`test_security_headers.py` EXPECTED updated to exact string (yes).
Follow-up demanded: sections/ inline-handler delegation lane.

## Commits (main, UNPUSHED at record time)
- `9e98662c` des-3: lucide re-guard (dom.js:22-26), hamburger null guards
  (base.js:319-322,331-332), history null guards (chat-history.js:103-106,136-139),
  inline-SVG favicon (sections/base.py:20). Reported (not edited, sections/ OOS):
  inline culprit `chat_layout.py:33` onload/onerror (= herta:651);
  password-form warnings (`chat_sidebar_core.py:31`, `chat_sidebar_media.py:154`).
- `2dad6556` fix-1: middleware CSP exact replacement + test update (4 passed).
- `284d9148` des-3: 61 inline handlers purged across 16 files (+449/-61);
  new `static/core/delegation.js` single-bind receiver; dead templates
  (persona.py, import_export.py) marked `data-dead-*`; password inputs wrapped in
  `<form data-password-form>`; sections grep for inline handlers → zero.

## Verification
- vitest 122 green (14 files, incl. new delegation.test.js 12), lint:js 65 clean,
  all sections .py py_compile OK, rendered HTML: data-action×24/mirror×39/
  toggle×5/form×2, handlers zero, avatar clean, favicon kept.
- Server restarted: old 51580 → new PID 65052, /health 200,
  live `Content-Security-Policy` header measured == oracle exact string.
- MCP nous via mcp-hub verified: `memory_stats` → 3164 memories, tagged_ratio 1.0;
  `get_context` → herta state restored (session-start routine retroactively done).
- Pre-existing noise (kept): Qdrant health-check warning (Qdrant :6333 down,
  connection refused), HF token warning, utcnow DeprecationWarning.

## Pending (external)
- User real-browser reload + console recheck.
- Push: 9e98662c, 2dad6556, 284d9148.

## Lessons
- des-1/des-2 resume wedged ("already owned by another lifecycle operation");
  recovered later as reusable; fresh des-3 carried the lane. Never resume wedged
  sessions — spin fresh.
- Orchestrator shell clumsiness: 55-sequential-request probe got (rightly)
  aborted by user; 3-file targeted probe + CDN HEAD sweep worked. Keep shell
  probes small with short timeouts.
- agent-browser `open` with load-wait hangs at about:blank (SPA); go straight
  to snapshot, ban browser tools for code-only lanes.
- Q3 contract vs implementation diverged silently (tests asserted the wrong
  minimal strings). Security-header changes need live-header measurement,
  not just unit green.
