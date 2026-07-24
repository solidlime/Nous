# TODO — Phase 10: Usability Hardening — Keyboard Accessibility

## Increment 1: スキップリンク + CSS
- [ ] `sections/base.py` — `<body>`直後にスキップリンク追加
- [ ] `styles/` — `.skip-link` CSS追加（focus時表示）
- [ ] コミット: `feat: add skip-link for keyboard accessibility`

## Increment 2: モーダル フォーカストラップ
- [ ] `core/modal.js` — フォーカストラップ実装
- [ ] `core/modal.js` — aria属性動的付与
- [ ] `core/modal.js` — フォーカス復元
- [ ] コミット: `feat: add focus trap and aria attributes to modal`

## Increment 3: タブナビゲーション キーボード
- [ ] `base.js` — タブa11y実装（role, tabindex, 矢印キー）
- [ ] コミット: `feat: add keyboard navigation to tabs`

## Increment 4: トースト + フォーム + チャット a11y
- [ ] `core/toast.js` — aria-live/role確認
- [ ] `features/settings/` — フォームラベル確認
- [ ] コミット: `feat: add accessibility attributes to toast and forms`

## Increment 5: 全ボタンキーボード対応
- [ ] アイコンボタンのキーボードハンドラ確認
- [ ] コミット: `feat: ensure all interactive elements are keyboard accessible`
