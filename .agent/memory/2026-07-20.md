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
- **チャットストリーミングのrAFバッチ**: text_deltaが高頻度（50-100回/秒）で来る場合、DOM書き込みを `requestAnimationFrame` でバッチ化しないとUIが詰まる。
- **自動スクロールの意図検出**: ユーザーが過去メッセージを読んでいる時に新しいトークンでスクロール位置を奪わないよう、`scroll` イベントで最下部からの距離を監視する必要がある。閾値80px。

## ディレクトリ構造リファクタリング (2026-07-20)
- `data/memory/{persona}/` → `data/persona/{persona}/` にペルソナデータを集約。Docker内データルート `/opt/nous` → `/data`。
- **Oracleレビュー必須**: 設定エイリアス（`data_dir` → `persona_dir`）は表面上コードが動くためgrepでの参照漏れ検出が不可能。Oracleレビューが6ファイルの致命的見落とし（use_cases, auto_import, cli, admin, runtime_config, tests）を発見。パス書き換えではOracleレビューを必ず計画に含めること。
- **データ移行の安全手順**: (1)サーバ停止、(2)ファイル移動、(3)サーバ起動。`ensure_directories()` が起動時に空ディレクトリを作るため、移動前に起動すると不整合が発生する。
- **Dockerボリュームマウント変更は破壊的変更**: `/opt/nous` → `/data` の変更はリリースノートと移行手順が必須。docker-compose.yml の volumes も必ず更新対象に含める。
- `skills_dir` をハードコード `/opt/nous/skills` → 動的 `{data_root}/skills` に変更。Dockerfile の COPY 先も同時更新必須。
