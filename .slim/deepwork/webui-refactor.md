# WebUI Refactor — Deepwork Tracker

**Start:** 2026-07-15
**Plan:** docs/superpowers/plans/2026-07-15-webui-refactor.md
**Oracle Review:** ses_09d626b4fffexv6uPpwSYbJrhl — BLOCK (conditional), 12 issues

## Phase Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Foundation (namespace + core modules) | 🔄 in_progress | |
| 2. Adapter + wire-up | ⏳ pending | |
| 3. Chat.js split | ⏳ pending | |
| 4. Constants consolidation | ⏳ pending | |
| 5. State store (pub/sub) | ⏳ pending | |
| 6. DOM safety | ⏳ pending | |
| 7. Usability hardening | ⏳ pending | |
| 8. Frontend tests | ⏳ pending | |
| 9. Backward compat removal | ⏳ pending | |

## Key Decisions
- No bundler — IIFE + `Nous.*` namespace
- Adapter layer for backward compat during migration
- Pure extraction in Phase 3 — no logic changes
- All features preserved: Equipment, TTS, Portrait
