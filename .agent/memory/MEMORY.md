# MEMORY

## 画像生成パイプライン全面リライト (2026-08-01)
- **commits**: 3e3df71, 590bc9c, d9b0b9e, 7cc3427
- **背景**: 動的ビルド `_build_workflow()` のノードID衝突（LoRAチェーン next_id=12 と img2img VAEEncode の上書き）→ ComfyUI で `LoraLoader 13: tuple index out of range`
- **方針**: テンプレートモード正規化（`workflows/default_node.json`）・動的ビルド全削除（テンプレート空→ValueError）・生成モード i2i 限定（`image_gen_mode` 削除）・speed_lora 全面撤去・`reference.png` 常時必須（t2i フォールバック廃止）
- **変更**: comfyui.py（_build_workflow 削除、_DEFAULT_NEGATIVE_PROMPT 定数集約）、tool_config.py、builtin.py（checkpoint直書き削除）、image_gen.py、UI 3ファイル、test_comfyui_provider.py
- **検証**: image_gen 系テスト 43 passed / 残留参照ゼロ / node --check OK

### 教訓
1. **ノードID衝突の根本対策は「動的ビルドを作らない」**: 動的採番は後から機能追加でID衝突を招く。テンプレート正規化で構造を静的保証。
2. **既存失敗の切り分けは stash 比較**: `nous/` を HEAD に戻してテスト → 失敗セット完全一致なら既存問題。作業中の失敗と混同しない。
3. **破壊的変更は複数コミット分割 + `[skip-docs]`**: refactor / test / feat(ui) を分離。docs 未更新は明示。
4. **UI機械的削除とバックエンドは並列 fixer**: 両者独立（UI=削除のみ、BE=ロジック）なので並列実行可能。write スコープ非重複を確認してから。
5. **persona config.json は root 所有**: ホストから直接編集不可（PermissionDenied）。`docker exec nous python3` で JSON 編集する。
6. **workflow_template 空設定の危険**: 必須化後、既存 config の空テンプレートは ValueError になる。デフォルト config は `workflows/default_node.json` に揃えること。

## Chat Pipeline SSE 無反応バグ修正 (2026-07-25)
- **commits**: bcbc633, 455a7c6
- **症状**: Webチャットでメッセージ送信後「記憶処理中...」のまま無反応
- **Root cause**: (1) `chat_stream.py` で `ctx.search_engine` が Qdrant 初期化失敗時に None になるのに `set_persona()` を無チェックで呼 → AttributeError → SSE 空切断、(2) `service.chat()` に catch-all try/except がない
- **Fix**: search_engine None ガード、(2) chat() 全体 try/except + ErrorSSE、(3) prepare.py の asyncio.gather に return_exceptions=True

### 教訓
1. **SSEストリーミングの catch-all 必須**: 最初の yield 以降の例外は自動で ErrorSSE にならない。全体を try/except で包む。
2. **asyncio.gather の return_exceptions**: デフォルト False は1つのタスク失敗で全結果喪失。安全側に倒す。
3. **外部依存の None 伝播**: Qdrant 失敗で None になるパターンは全呼び出し元でチェック必須。

## ドッグフーディングテストの注意点 (2026-07-25)
- テストはローカル、配信はDockerイメージ（`ghcr.io/solidlime/nous:latest`）。コード修正後のテスト手順: 修正 → `docker build` → `docker compose down && up -d` → ブラウザ検証。

## ChatConfig 分割 + 契約テスト + CI強化 (2026-07-25)
- **commits**: f4627f3〜8bc43a7, 65ffe5e
- ChatConfig 4サブ設定分割（Provider/Session/Compression/Tool）、Facade で後方互換。Pact契約テスト18件、coverage 70% + bandit。

### 教訓
1. **Pydantic Facade with __getattr__**: サブ設定をPydantic内包でも `__getattr__` で透過アクセス可能。
2. **Pact fixture スコープ**: pact-python v3.4.0 は同一インスタンス複数 serve() でFFI競合 → fixture scope を function に。
3. **fixer がコミットし忘れるケース**: Git操作の最終確認は orchestrator が行うこと。

## コード清掃 — 大規模ファイル分解 (2026-07-25)
- **5並列 fixer**: 5ファイル→13ファイル（+2934/-3093行）、import検証 PASS、ruff クリーン。session_store(809)→3、memory_repo(776)→3、prepare(748)→3、compress(425)→2、memory_llm(487)→2。
- **教訓**: 並列 fixer は大規模分解に有効。Mixin パターン（単一クラス分割）vs 再エクスポート（独立クラス群）を状況で使い分け。

## WebUI リファクタリング完了 (2026-07-25)
- 29 JS→38 JSモジュール、`N.*` 名前空間統一、Pub/Sub store完備、`store.syncFrom()` 双方向同期、DOMPurify統一、モバイル対応、a11y強化。15フェーズ/50+コミット。
- **教訓**: `Object.defineProperty` で双方向同期を透過実装 → 49箇所の直接参照修正不要。機能タブ分割はモノリシック HTML はスタブ化が限界。CSS分割は `@layer` とロード順管理が鍵。

## Portrait Feature Removal (2026-07-18)
- 13ファイル削除 + 25ファイル部分削除。教訓: feature removalでは定義と参照の両軸で確認（grep後に動的参照・未使用定数の見落とし防止）。

## ディレクトリ構造リファクタリング (2026-07-20)
- `data/memory/{persona}/` → `data/persona/{persona}/`。Docker内データルート `/opt/nous` → `/data`。
- **教訓**: 設定エイリアスはgrepでの参照漏れ検出が不可能 → Oracleレビュー必須。データ移行は (1)サーバ停止 (2)ファイル移動 (3)起動 の順。

## コードリファクタリング (2026-07-20) — 約-415行
- 5つの `SQLite*Repository` 基底クラス集約、`compute_exponential_decay()` 統合、conftest.py フィクスチャ集約(-109行)、過剰try/except除去。
- **教訓**: 同一シグネチャ __init__ が3つ以上で基底クラス抽出。コピペと思ったら共通化。MCPツールエラー形式の表記揺れは初期に統一規約。

## 内臓スキル5種 自律動作テスト (2026-07-22)
- **最終モデル**: `nvidia/nemotron-3-ultra-550b-a55b:free`（55B active, 1M context）。5/5合格。
- **教訓**: OpenRouterの無料モデルは永続的でない（hy3:free, qwen3-coder:free は404）。temperature=0 が小規模モデルのツール呼出に必須。テスト間のセッションIDはUUIDで分離。

## クロススキル連鎖の汎用化 (2026-07-22)
- 特定ペア最適化ではなく全ツール間連鎖マトリクスを `<cross_skill>` に定義。画像生成の予告禁止（「黙って呼べ」）は全スキル共通ルール。

## プロンプト設計の層分離原則 (2026-07-22)
- システムプロンプト = 行動指針 + スキル発見（name+descriptionのみ）/ スキル内容 = 具体ツール名・連鎖指示 / API tools = 型情報。効果: ~680→~300文字。

## ペルソナ非依存パイプライン設計 (2026-07-22)
- パイプライン層は事実のみ伝達。感情的反応はペルソナ定義と mood-sync に委ねる。共有コードにペルソナ固有の口調を埋め込むな。

## 時間経過検知 5段階自律チェーン検証 (2026-07-22)
- Nemotron Super 120B で TIME_CONTEXT→mood-sync→update_context→image-gen→memory_create の全段階を1ターンで完遂。
- **DB設計**: `_resolve_last_conversation_time()` は memories テーブル最新タイムスタンプ最優先。テスト時は memories クリア＋古いエントリ挿入が必要。
- 小規模モデルではツールチェーンとテキスト応答の一貫性が保証されない（モデル品質依存）。

## テストモデル: openrouter/free (2026-07-22)
- 特定モデル固定ではなく `openrouter/free` 自動ルーティング（無料モデルは予告なく終了するため）。

## Thinking トグル + effort 設定 (2026-08-08)
- **commits**: 1b366af（BE+テスト）, b575067（UI）, 19d5a8b（docs）
- **背景**: チャット LLM の thinking on/off トグル + ヴァリアント（effort）スライダー。SPEC: `.spec/SPEC-thinking-toggle.md`
- **設計**: 設定は統一 4 段階 effort（low/medium/high/max）+ on/off を保持し、プロバイダ実装側で変換（OpenRouter: `reasoning:{effort}` / OpenAI: `reasoning_effort` / Anthropic: budget_tokens 2048-16384）
- **検証**: 新規テスト 17 passed。ブラウザ実機確認（puppeteer/Tailscale IP）でトグル・スライダー・保存・リロード復元すべて確認

### 教訓
1. **テストはシステム python3（rtk pytest）で実行**: `.venv/bin/python` には openai/anthropic が無い（ModuleNotFoundError）。システム python3 には openai 2.44.0 / anthropic 0.116.0 がある。
2. **ブラウザ実機確認のパターン**: リモートブラウザからは localhost 不可 → Tailscale IP（100.112.180.92:26262）+ headless + --no-sandbox + allowDangerous。タブ切替は `[data-tab]` の可視ボタンをクリック（#tab-chat 直クリックは active にならない場合あり）。保存フローは fetch フックで payload 確認 → API GET でサーバー反映確認 → リロード復元確認。
3. **UI 新設定の実装は既存パターン踏襲**: 動的温度調整（checkbox + slider.disabled + oninput ラベル同期）の踏襲で統一感を保つ。updateSliderLabels の実体は chat-settings-image.js（chat-settings.js ではない）。
4. **ブラウザ検証で書き換えた persona config は検証後に元に戻す**（API POST で復元）。
