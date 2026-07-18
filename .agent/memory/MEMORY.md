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
