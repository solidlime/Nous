# TODO — Phase 10: Usability Hardening — Keyboard Accessibility ✅

## Update (2026-07-25): 完了
- スキップリンク (base.py) は既存。hrefを `#tab-content` → `#main-content` に修正、main要素にid+tabindex="-1"付与 ✅
- モーダル (core/modal.js) は全て完了済み（フォーカストラップ、aria、Escape、復元） ✅
- チャットはEnter/Shift+Enter問題なし ✅
- 不足項目のみ実装:

### Increment 1: スキップリンク修正 + aria属性追加
- [x] `sections/base.py` — skip-link href `#tab-content` → `#main-content`、mainに id+tabindex="-1"
- [x] `core/toast.js` — fallback containerに aria-live/role/aria-atomic、各toastに role="status"
- [x] `features/settings/settings-form.js` — validation error divに role="alert"
- [x] コミット: `bacad16` — feat: add skip-link target, toast aria/role attrs, settings validation role=alert

### Increment 2: タブ矢印キーナビゲーション
- [x] `base.js` — ArrowLeft/ArrowRight でタブ切替（WAI-ARIA tabs pattern）
- [x] コミット: `3468506` — feat: add arrow key navigation for tabs (Left/Right)

### Increment 3: activity.js キーボード対応
- [x] `features/activity.js` — セッションヘッダーに tabindex="0" role="button"、Enter/Space keydown
- [x] コミット: `c4f54db` — feat: add keyboard support for activity session headers
