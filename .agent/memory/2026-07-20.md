# MEMORY

## Portrait Feature Removal (2026-07-18)
- **削除ファイル**: Python 6件、JS/CSS 4件、テスト 3件 = 13ファイル
- **部分削除ファイル**: 25ファイル（Python backend, JS frontend, HTML sections, docs）
- 教訓: feature removalではgrep後に動的参照・未使用定数・CSSスタイルの見落としが発生しやすい。定義と参照の両軸で確認すること。

## Sudachi Dict Runtime Download (2026-07-18)
- `sudachidict_core` (~208MB) をランタイムダウンロードに切り替え、イメージサイズ 982→774MB (-21%)
- 辞書保存先: `{NOUS_DATA_ROOT}/sudachi/system_core.dic`

## Toast / SSE Timing 教訓 (2026-07-20, v3.5.0)
- **JSのsetTimeout削除とCSSアニメーションの競合**: `setTimeout(3200)` で要素削除するより `animationend` イベント（`{ once: true }`）を使う方がCSSと正確に同期する。setTimeoutはフォールバックとして残す。
- **safe-area-inset対応**: モバイルのノッチ・ホームインジケータ対策には `env(safe-area-inset-*)` が必須。特に下部通知系UIでは `padding-bottom` に加算すること。
- **チャットストリーミングのrAFバッチ**: text_deltaが高頻度（50-100回/秒）で来る場合、DOM書き込みを `requestAnimationFrame` でバッチ化しないとUIが詰まる。
- **自動スクロールの意図検出**: ユーザーが過去メッセージを読んでいる時に新しいトークンでスクロール位置を奪わないよう、`scroll` イベントで最下部からの距離を監視する必要がある。閾値80px。
