# SPEC — Phase 10: Usability Hardening — Keyboard Accessibility

## 背景
Phase 5 で `N.Components.modal.*` が利用可能、Phase 8 で CSS 分割済み、Phase 9 で空/エラー状態が追加済み。
キーボード操作対応が未整備のため、アクセシビリティ対応を施す。

## 修正項目

### 1. タブナビゲーション
**対象**: `features/graph.js`, `features/timeline.js`, `features/activity.js`, `base.js`
- `role="tablist"` をナビゲーションタブコンテナに付与
- 各タブに `role="tab"`, `tabindex`, `aria-selected` を付与
- ← → 矢印キーでのタブ切り替え
- Enter/Space で選択

### 2. モーダル（core/modal.js）
- 表示時: フォーカスを最初のフォーカス可能要素へ
- Tab/Shift+Tab: モーダル内で循環（フォーカストラップ）
- Escape: 閉じる
- `role="dialog"`, `aria-modal="true"`, `aria-labelledby` 動的付与
- 閉じた時: フォーカスを表示前に戻す

### 3. チャット入力（chat/chat-core.js / chat-send.js）
- Enter: 送信, Shift+Enter: 改行（既存確認）
- フォーカス常に到達可能確認

### 4. 設定パネル（features/settings/）
- 全フォーム要素に `label`（for属性）または `aria-label`
- バリデーションエラー: `role="alert"`

### 5. トースト通知（core/toast.js）
- `aria-live="polite"` + `role="status"` 確認・追加

### 6. スキップリンク（sections/base.py + 対応CSS）
- `<body>` 直後に「メインコンテンツへスキップ」
- 最初のTabで出現
- クリックで `#main-content` にフォーカス
- CSS: `.skip-link`（focus時のみ表示）

### 7. 全ボタン/インタラクティブ要素
- onclickのみの要素に `tabindex="0"` + keydown（Enter/Space）追加
- 特にlucideアイコンボタン確認

## 変更ファイル
- `core/modal.js` — フォーカストラップ、aria属性、Escape
- `core/toast.js` — aria-live/role確認
- `base.js` — タブキーボード操作
- `sections/base.py` — スキップリンク
- `features/graph.js` — タブa11y
- `features/timeline.js` — タブa11y
- `styles/*.css` — `.skip-link`, `focus-visible`

## 検証
1. `npm test` → 71 PASS維持
2. 新規コード構文確認（grep）
