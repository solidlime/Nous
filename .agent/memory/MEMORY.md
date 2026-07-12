# MEMORY

## 設計パターン

### ONNX Runtime 直叩きによる PyTorch 完全排除（2026-07-12 学習）
- **背景**: `sentence-transformers` → ONNX Runtime への置き換えで PyTorch を依存から外した
- **選択肢**: `optimum-onnx`（torch間接依存で不適）、`fastembed`（Ruri v3未サポート）、`txtai`（embeddings ONNX非対応）— 全滅。ONNX Runtime直叩き一択だった
- **実装**: `onnxruntime.InferenceSession` + `tokenizers.Tokenizer`（Rust製、torch非依存）
- **モデル**: `onnx-community/ruri-v3-30m-ONNX`（公式ONNX版）、reranker: `hotchpotch/japanese-reranker-xsmall-v2`（ONNX内蔵）
- **トークナイザー罠**: LlamaTokenizer (SentencePiece) は `post_processor` が既に `<s>` + text + `</s>` を自動付与 → 手動TemplateProcessing不要。Phase 0事前検証で発見
- **Pooling戦略**: Ruri v3 ONNX は生の `last_hidden_state` 出力 → mean pooling (attention_mask加重) → L2 normalize を自前実装
- **コード変更量**: model.py 285行、reranker.py 218行に完全書き換え。公開APIは1行も変更なし
- **テスト**: 1621 passed / 7 skipped。rerankerテストは `_model.predict` → `_session.run` モック更新が必要だった

### optimum-onnx vs optimum のtorch依存の罠（2026-07-12 学習）
- 2025年末に `optimum` から `optimum-onnx` にONNX関連コードが分離された
- **だが** `optimum-onnx` の `pyproject.toml` は `optimum~=2.2.0` を必須依存としており、これが `torch>=1.11` を要求
- 結果として `optimum-onnx` を入れても間接的にtorchが入る → PyTorch排除の目的に反する
- **結論**: 「PyTorchフリー」を謳っていても依存ツリーの末端まで確認しないとダメ

### 設定のグローバル vs ペルソナ毎の境界線（2026-07-11 学習）
- **Settings (グローバル/env)**: インフラ共有資源 + 公開情報 (DB URL, API endpoint, サーバーバインド等)
- **ChatConfig (per-persona)**: ペルソナの行動選択 + クレデンシャル (enabled フラグ、ペルソナ固有 API キー等)
- **核心**: `enabled` はペルソナの「意志」の領域。グローバル固定は強制。

### フォールバックパターンの鉄則
新機能追加時は「**既存ユーザーへの後方互換**」を常に維持:
- `chat_config.irodori_enabled or ctx.settings.irodori.enabled` の OR フォールバック
- 新カラム追加時は `DEFAULT 0` / `DEFAULT ''` で安全側に倒す
- 旧 Settings のキーは**残す**（CLI からの有効化用）

### Docker socket 露出の影響評価
- `opensandbox` サービスが既にマウントしている socket を `nous` にも追加することは、**信頼境界の拡張であり、新たな境界を開くわけではない**

## 失敗パターン

### 大規模依存削除の手順（2026-07-11 学習）
1. アプリケーションコードの参照（import・関数呼び出し・定数）
2. スキーマ定義（CREATE TABLE・migration ALTER TABLE）
3. 設定定義（Settings フィールド・RuntimeConfig SETTINGS_META）
4. 依存定義（pyproject.toml dependencies）
5. テストファイルの参照・テストファイル自体の削除
6. ファイル削除（削除予定ファイルへの import が残っていないか確認）
- 削除後は必ず `ruff check nous/ tests/` と `ruff format --check nous/ tests/` の両方を CI と同じ条件で実行

### 環境変数名不一致（2026-07-11 学習）
- **設定の読み取りロジックを grep で確認**してから env 名を決定。プレフィックスは settings.py の `env_prefix` を尊重

## 運用ルール

### コミット粒度の指針
- 機能単位（feat / fix / chore）で 1 コミット
- ドキュメント反映（docs:）は別コミット
- 仕様駆動の成果物（`.spec/`）も別コミット
- HANDOFF 更新は別コミット

### fixer への指示テンプレ（2026-07-11 確立）
1. 背景・設計の最終決定（Oracle レビュー結果を反映）
2. 採用するアーキテクチャ（図示）
3. 環境変数（必須/オプション一覧）
4. 既存コードの重要事実
5. 実装スコープ（タスク番号、ファイルパス）
6. TDD 適用（RED→GREEN→REFACTOR）
7. 検証ゲート（ruff, pytest）
8. テストスコープ制限（自身の変更ファイルのみ）
9. コミット
10. 報告

### submit ボタンの onclick 内 disabled 禁止（2026-07-12 学習）
- `onclick="this.disabled=true"` は Chrome/Safari でフォーム送信ごとキャンセルする
- ブラウザが「有効な submit ボタン無し」と判断 → `onsubmit` が発火しない → 一切の処理が動かない
- **対策**: ボタン無効化は必ず `onsubmit` ハンドラ内で行う（submit イベントの発火を確認してから）
- Playwright で実ブラウザ検証して確定

### HTML5 pattern 属性と v フラグの罠（2026-07-12 学習）
- HTML5 `pattern` 属性の正規表現はブラウザが `v` フラグ（Unicode Sets モード）で評価する
- `v` フラグでは `-` がレンジ演算子として厳密に扱われる → `[a-zA-Z0-9_-]` はエラー（`_-` = 逆順レンジ）
- エラーになるとブラウザはパターン検証を**完全無効化**（常に valid）→ クライアントサイドバリデーションが死ぬ
- **対策**: `-` は必ず `\-` でエスケープ（`[a-zA-Z0-9_\-]`）
- **Python の `re.compile` では再現しない**（v フラグ非対応）。必ず実ブラウザでテストすること

## ツール別 Tips

### Playwright MCP Docker 起動の罠
- イメージのデフォルト ENTRYPOINT が `["node", "/app/cli.js", "--headless", "--browser", "chromium", "--no-sandbox"]` で `--port` がない
- **stdio モードで起動** → Docker デタッチドでは stdin 即 EOF → exit(0) → restart loop
- 修正: `entrypoint: ["node"]` + `command` で全引数明示 + `--port 8931 --host 0.0.0.0 --allowed-hosts *`

### opensandbox の環境変数
- `OPENSANDBOX_INSECURE_SERVER=YES` — 非対話モードで API キー空を許可（必須）

### SearXNG URL 解決
- `docker-compose.yml` → `NOUS_SEARXNG_URL` を使う（`SEARXNG_URL` ではない）
