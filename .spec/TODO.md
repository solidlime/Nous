# TODO — Phase 11: Mobile Responsiveness (2026-07-25)

## ベースライン: 390×844, 768px未満

## Increment 1: ハンバーガーメニュー + ナビゲーション
- [ ] `base.js` — ハンバーガーボタン生成（init()内）、ドロワーメニューの開閉ロジック、バックドロップ、Escape/メニュー外クリック閉じる
- [ ] `styles/layout.css` — 768px未満でtab-bar隠し、ハンバーガーボタン表示、ドロワーメニューアニメーション
- [ ] コミット: hamburger menu with drawer navigation

## Increment 2: テーブルレスポンシブ + メモリカード
- [ ] `nous/api/http/sections/skills.py` — <th> と <td> に data-label 属性追加
- [ ] `styles/components.css` — @media (max-width: 767px) テーブルカードビュー、メモリカード1カラム、44pxタップターゲット
- [ ] コミット: responsive tables and memory cards

## Increment 3: チャット設定パネル（モバイルオーバーレイ）
- [ ] `chat/chat-settings.js` — モバイル用タイトルバー・閉じるボタン
- [ ] `styles/chat-mobile.css` — 全画面オーバーレイ + 固定保存ボタン
- [ ] コミット: chat settings panel mobile overlay

## Increment 4: トーストモバイル調整 + 全般モバイル調整
- [ ] `core/toast.js` — スワイプ消去、最大2制限
- [ ] `styles/components.css` — トーストモバイルスタイル
- [ ] `styles/layout.css` — max-width:100vw防止、フォームモバイル、ペルソナセレクター拡大、prefers-reduced-motion確認
- [ ] コミット: mobile toast and general responsive adjustments

## Increment 5: vis.js モバイル調整 + フォームモバイル
- [ ] `features/graph.js` — matchMedia で物理演算調整
- [ ] `features/timeline.js` — モバイル時ズーム調整
- [ ] `features/settings/settings-form.js` — フォームモバイルレイアウト
- [ ] コミット: vis.js mobile physics and form mobile layout

## 検証
- [ ] `cd nous/api/http/static && npm test` → 71 PASS
- [ ] CSS lint: `npm run lint:css` → PASS
