# MEMORY

## Portrait Feature Removal (2026-07-18)

### Scope
- **削除ファイル**: Python 6件、JS/CSS 4件、テスト 3件 = 13ファイル
- **部分削除ファイル**: 25ファイル（Python backend, JS frontend, HTML sections, docs）
- **全コミット**: 5 commits, ~600行削除

### Lessons Learned

1. **Frontend/backend feature removal では dead code の見落としが発生しやすい。** `grep -rn` で全ファイルを確認した後でも、動的参照（`typeof renderOverviewPortraitSection === 'function'`）や未使用定数（`EMOTION_COLORS_PORTRAIT`）が残っていた。最終確認は定義と参照の両軸で行うこと。

2. **イベントバス定数の削除漏れはコンパイルエラーにならない。** `event_bus.py` の `PORTRAIT_GENERATE_*` 定数は他のコードが参照していなかったため、grep で検出できても気づきにくい。feature removal では全定数の grep と、イベントハンドラの削除を合わせて行う。

3. **Settings/Config の削除は影響範囲が広い。** 設定クラスを削除すると runtime_config.py, settings.py, 該当 env 変数, フロントエンドの設定UI表示まで一貫して消す必要がある。

4. **CSS スタイルの削除漏れは目視では見つけにくい。** HTML の該当ブロックを削除しても、CSS ファイルに未使用スタイルが残る。`grep` で「`portrait`」を引いて全CSSファイルを確認するクセをつける。

## Sudachi Dict Runtime Download (2026-07-18)

### Summary
- `sudachidict_core` (~208MB) を pip パッケージから削除し、初回起動時にランタイムダウンロードへ切り替え
- 辞書保存先: `{NOUS_DATA_ROOT}/sudachi/system_core.dic`（ホストマウント永続化）
- ダウンロード元: `https://github.com/WorksApplications/SudachiDict/releases/download/v20260428/sudachi-dictionary-20260428-core.zip`
- イメージサイズ: ~982MB → ~774MB（-208MB, 約21%削減）

### Key Decisions
1. **`Dictionary(dict=絶対パス)` でカスタムパスからロード**（pipパッケージ不要）
2. **ダウンロードは `urllib.request` + `zipfile` で実装**（追加依存なし）
3. **`NOUS_DATA_ROOT` 環境変数でパス制御**（Docker/Dockerfileどちらでも一貫）

### Notes
- 初回 `extract_accurate()` 呼び出し時に~72MBダウンロードが発生するため、初回のみ遅延あり
- Reranker/Embeddingモデルはすでに `HF_HOME` 経由でホスト永続化済み（変更不要）
- `docker-compose.yml` の `DATA_ROOT:/opt/nous` マウントで辞書も自動永続化される
