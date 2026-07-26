# HANDOFF — 2026-07-25 (Phase 12: Window Pollution Removal — COMPLETE)

## セッション概要
Phase 12: 全モジュールの `window.*` エクスポートを除去し `N.*` 名前空間のみに統一。

## 完了コミット（2 commits）
```
49f90b8 refactor: remove window.* pollution, migrate to N.* namespace
21d0c6e fix: update Python section onclick refs to N.* namespace
ded6ebf fix: update JS inline onclick refs from bare names to N.* namespace
```

## 変更ファイル（43 files, +312/-351）
### core/*.js (window backward compat exports removed)
- `api.js`, `dom.js`, `modal.js`, `sse.js`, `theme.js`, `time.js`, `toast.js`
- `dom.js`: `N.Core.safeSetHTML` 関数定義を保持（誤削除から復元）
- `dom.test.js`: `window.safeSetHTML` → `N.safeSetHTML`

### features/*.js (window exports removed, N.Features.* registration → onclick fixes)
- `graph.js`, `timeline.js`, `activity.js`, `memories-core.js`, `memories-edit.js`
- `overview-core.js`, `settings-core.js`, `settings-form.js`, `settings-save.js`
- 全inline onclick文字列を bare function → `N.Features.*` に修正
- `memories-edit.js`: `onclick="closeMemModal()"` → `N.Features.Memories.closeMemModal()`

### chat/*.js (window exports removed, N.Chat.* sub-namespace registration → onclick fixes)
- 12 chat files modified, each registered on appropriate N.Chat.* namespace
- Cross-module references fixed: `safeSetHTML`, `safeMarkdown`, `appendChatMessage`, etc.
- `chat-history.js`: `onclick="toggleSettingsPanel()"` → `N.Chat.core.toggleSettings()`

### Python sections (onclick → N.* namespace, 16 handlers updated)
- `chat_layout.py`: 10 handlers → `N.Chat.*`
- `chat_sidebar.py`: 15 handlers → `N.Chat.*` (incl. `N.Chat.tts.test`, `N.Chat.settings.save`, `N.Chat.history.clear`)
- `timeline.py`: 2 handlers → `N.Features.Timeline.*`
- `memories.py`: 4 handlers → `N.Features.Memories.*`
- `activity.py`: 1 handler → `N.Features.Activity.*`

## リマインダー（安全のための制約）
### base.js / base.py は Phase 13 まで触らない
- base.js 内の `window.foo = ...` アダプター行（~40行）
- base.py の `window.__INITIAL_PERSONA__` および base.py 内の全onclick
- これらは Phase 13 で一括除去する

### 安全に残っている参照
- `var S = window.S;` — store 同期用（安全）
- `var { esc, api, ... } = window.Nous.Core;` — N.* destructure（安全）
- `window.open()`, `window.innerWidth`, `window.matchMedia()`, `window.dispatchEvent()`, `window.addEventListener()` — ブラウザネイティブAPI
- `window.SpeechRecognition / window.webkitSpeechRecognition` — ブラウザネイティブAPI
- Python sections の inline スクリプト内関数（persona.py, skills.py, import_export.py） — 同一ページコンテキストで定義

## テスト
- 71/71 pass（`npm test`）
- 7 test files, all passing
