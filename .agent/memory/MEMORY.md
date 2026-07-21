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
- 5つの `SQLite*Repository` の `__init__`+`_db` パターンを `SQLiteRepository` 基底クラスに集約。
- 教訓: 同一シグネチャの `__init__` が3つ以上あれば基底クラス抽出を検討せよ。

### ドメインロジック重複統合
- `body_decay.py` と `emotion_decay.py` の指数関数的減衰計算を `compute_exponential_decay()` に統合。
- 教訓: コピペと思ったら迷わず共通化。

### MCPツールエラー形式の表記揺れ
- `_tools_memory.py` だけ `json.dumps({"ok": False, ...})`、他3ファイルは `{"success": False, ...}`。
- 教訓: 初期実装時に統一規約を作るべき。後修正はテストアサーション変更を伴う。

### テストフィクスチャ集約
- 14ファイルで同一フィクスチャ再定義 → conftest.py 1箇所に集約 (-109行)。

### 過剰try/exceptの除去
- `memory_repo.py` の参照系から try/except 除去 (27→8個, -85行)。

### Result伝播パターンは許容
- `if not result.is_ok: return Failure(result.error)` はRustの `?` 相当。抽象化すると可読性を損なうので許容。

## 内臓スキル5種 自律動作テスト (2026-07-22)
- **最終モデル**: `nvidia/nemotron-3-ultra-550b-a55b:free`（55B active, 1M context）
- `tencent/hy3:free` と `qwen/qwen3-coder:free` は無料期間終了で404。
- **結果**: 全5スキルが invoke_skill → 対象ツールのチェーンを達成（5/5合格）。

### 教訓
1. **OpenRouterの無料モデルは永続的でない**: ライブ確認が必須。テスト直前に存在確認すること。
2. **temperature=0 が小規模モデルのツール呼出に必須**: 決定論的動作でツール選択の一貫性が向上。
3. **プロンプトの命令形強化が効果的**: 「ツールを呼べ」「説明だけで済ませるな」の明示でモデルの行動が変わる。
4. **テスト間のセッションID一意性**: 同一session_idでコンテキスト汚染が発生。毎回UUIDで分離すること。
5. **Nemotron 3 Ultra はツール呼出に優秀**: 55B activeでも自律的スキル呼出を安定達成。レート制限（32 workers）に注意。

### 変更ファイル
- `data/persona/herta/config.json`: provider→openrouter, model→nemotron, temperature→0.0, enabled_skills修正
- `nous/application/chat/pipeline/prompt.py`: TOOL_USAGE_GUIDELINES強化、スキルヘッダー/末尾リマインダー改善
- `scripts/skill_test.py`: テストスクリプト新規作成
