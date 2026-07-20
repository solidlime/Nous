# MEMORY

## Portrait Feature Removal (2026-07-18)
- **削除ファイル**: Python 6件、JS/CSS 4件、テスト 3件 = 13ファイル
- **部分削除ファイル**: 25ファイル（Python backend, JS frontend, HTML sections, docs）
- 教訓: feature removalではgrep後に動的参照・未使用定数・CSSスタイルの見落としが発生しやすい。定義と参照の両軸で確認すること。

## Sudachi Dict Runtime Download (2026-07-18)
- `sudachidict_core` (~208MB) をランタイムダウンロードに切り替え、イメージサイズ 982→774MB (-21%)

## Toast / SSE Timing 教訓 (2026-07-20)
- **JSのsetTimeoutとCSSアニメーションの競合**: `animationend` イベント（`{ once: true }`）を使う方がCSSと正確に同期する。
- **チャットストリーミングのrAFバッチ**: 高頻度text_deltaのDOM書き込みは `requestAnimationFrame` でバッチ化。
- **自動スクロールの意図検出**: スクロール位置監視の閾値は80px。

## ディレクトリ構造リファクタリング (2026-07-20)
- `data/memory/{persona}/` → `data/persona/{persona}/`。Docker内データルート `/opt/nous` → `/data`。
- **Oracleレビュー必須**: 設定エイリアス（`data_dir`→`persona_dir`）はgrepでの参照漏れ検出が不可能。Oracleが6ファイルの致命的見落としを発見。
- **データ移行の安全手順**: (1)サーバ停止、(2)ファイル移動、(3)サーバ起動。`ensure_directories()` が起動時空ディレクトリを作るため逆順不可。

## コードリファクタリング (2026-07-20) — 合計約-415行削減

### Repository基底クラス抽出
- 5つの `SQLite*Repository` の `__init__`+`_db` パターンを `SQLiteRepository` 基底クラスに集約。`_db_method` クラス変数でDB切替（"get_memory_db" / "get_inventory_db"）に対応。
- 教訓: 同一シグネチャの `__init__` が3つ以上あれば基底クラス抽出を検討せよ。

### ドメインロジック重複統合
- `body_decay.py` と `emotion_decay.py` の指数関数的減衰計算を `compute_exponential_decay()` に統合。変数名が違うだけでロジックは同一だった。
- 教訓: コピペと思ったら迷わず共通化。インターフェースは `(current, target, half_life, elapsed, threshold)` で十分。

### MCPツールエラー形式の表記揺れ
- `_tools_memory.py` だけ `json.dumps({"ok": False, ...})`、他3ファイルは `{"success": False, "result_summary": ...}`。
- 教訓: 4ファイルの初期実装時に統一規約を作るべきだった。後からの修正はテストのアサーション変更を伴う。

### テストフィクスチャ集約
- 14ファイルで同一 `sqlite_conn` フィクスチャを再定義 → `tests/unit/conftest.py` 1箇所に集約 (-109行)。
- 教訓: プロジェクト初期に共通フィクスチャをconftest.pyに定義しておけば増殖を防げる。

### 過剰try/exceptの除去
- `memory_repo.py` の参照系（SELECTのみ）メソッド19個から try/except を除去 (27→8個, -85行)。
- 教訓: rollback不要な参照系メソッドの try/except は単なるノイズ。SQLiteのエラーは例外として上位層に伝播させれば十分。

### Result伝播パターンは許容
- `if not result.is_ok: return Failure(result.error)` の25+回の繰り返しはRustの `?` 演算子相当。Pythonでは言語サポートがないため2行パターンが限界。抽象化すると可読性を損なうので許容する。
- 教訓: すべての重複が悪ではない。言語の構造的制約による反復は抽象化するな。
