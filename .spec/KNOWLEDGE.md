# KNOWLEDGE: 全体評価・対策・教訓 2026-06-28 (v6)

## 評価から得た重要な知見

### ツール設計のアンチパターン（検出済み）
1. **「何でもツール」**: 1ツールに複数アクションを詰め込む（browser, sandbox_files）
2. **「双子ツール」**: 同一スキーマで説明文だけ違う（goal_manage/promise_manage）
3. **「破壊的更新」**: 曖昧検索→無言上書き（memory_update）
4. **「隠れた制限」**: 制限値がLLMに伝わらない（read_pdf等）
5. **「スキーマと実装の不一致」**: required不整合（sandbox_files）
6. **「長文description」**: LLMのツール選択精度低下

### 類似プロジェクト比較
- memstate-mcp: 7ツール、neuromcp: 検索品質◎、isaacriehm: supersede安全更新、Anthropic公式: 9ツールシンプル、danielsimonjr: 213ツールは反面教師

### 設計原則
1. 1機能1ツール 2. ツール数10前後 3. description1行 4. 制限値はLLMに見せる 5. 破壊的操作は2段階 6. required一致

### UI/UX アンチパターン（新規検出）🆕
1. **「発見不可能な高機能」**: スラッシュコマンド・ショートカットが一切UI表示されず、ソースコードを見た人しか知り得ない
2. **「沈黙の空状態」**: データ0件時に完全白紙。初回利用者に「何をすればいいか」の手がかりゼロ
3. **「CSSの断片化」**: Pythonヒアドキュメントに300行超のインラインスタイルが分散。CSSファイルが唯一のスタイルソースではない
4. **「ハードコードテーマ値」**: `rgba(255,255,255,0.06)` 等の固定値がテーマ変数を迂回し、ライト/ダーク切替を破綻させる
5. **「重複定義の放置」**: scrollbar スタイルが 2回定義され、先行定義がデッドコード化

### テストアーキテクチャの知見
- テスト0件の重要ファイル: memory_llm.py (571行), builtin.py handler 4件 (390行), definitions.py (309行)
- テスト0件の改修対象では、**必ずテストを先行作成してから実装に入る**
- 全grepで見つからない非文字列一致（JS変数名、HTML id、SSEフィールド名）の見落としに注意
- chat.js (1735行) はJSテストフレームワーク未導入のため手動確認のみ

### CSS保守性の教訓 🆕
- Pythonヒアドキュメント内の `style="..."` は grep で一括検索・置換が困難
- テーマ変数（`var(--glass-bg)`）で定義しつつ、実装では生の rgba 値を使う「二重管理」が破綻を生む
- `<style>` ブロックを HTML sections に書くと、読み込み順序の保証がなく予測困難

## 既存知見（継承）
- sections/ のJS/CSS静的ファイル分離完了（6,986→2,770行）
- 画像生成: DALL-E 3 + SD 両対応、base64統一
- PDF解析: PyMuPDF + pdfplumber + OCR (tesseract)
- pre-commit: lefthook に統一済み
- カバレッジ: 63→65%、長期目標70%

## emotion trigger_key 即時活用（2026-07-01）
- `update_emotion()` は `trigger_key` と `context` パラメータを持つが、全4呼出箇所で `None` 渡しだった（因果関係の喪失）
- 修正: 各呼出に `context` を設定（manual_update, llm_suggested, time_decay）
- 感情トレンド表示にコンテキスト情報を追記: `joy → sadness(time_decay) → anger(manual_update)`
- `memory_llm.py` はLLM提案の感情変更 → `context="llm_suggested"`（現時点ではtrigger_memory_keyなし）
- `emotion_decay.py` は時間減衰 → `context="time_decay"`（trigger_memory_keyは恒久的にNone）
- 教訓: DBスキーマにあってもコード経路でデータが流れていないパターンが多い。oracle audit で検出可能。

## read_pdf パス解決（2026-07-01）
- Nous は Docker 2コンテナ構成（nous + sandbox）で sandbox ファイルは別コンテナの `/home/sbox_*/` に存在
- `read_pdf` は nous コンテナ内の `Path.exists()` でチェック → sandbox パスは常に存在しないと判定
- 修正: `/home/sbox_*` / `/sandbox` で始まるパスを sandbox session 経由で読み取り、bytes で PyMuPDF に渡す
- `_sync_process_pdf` は `str | bytes` を受け付けるよう拡張。`fitz.open(stream=bytes, filetype="pdf")` で in-memory 処理
- エラーメッセージを日本語→英語に統一（既存の他ツール英文化と一貫）

## sandbox 単一コンテナ移行の知見 🆕

### 技術的教訓
- `llm_sandbox` のマルチコンテナ管理は複雑性が高く、単一コンテナ + `docker exec` 方式で十分なユーザー分離が可能
- `docker.from_env().containers.get("sandbox").exec_run(code, user=username)` でLinuxユーザー権限分離がシンプルに実現できる
- `DAC_OVERRIDE` ケーパビリティ追加で、ユーザー所有でないファイルの読み取りが可能（sandbox共有に必要）

### 実装パターン
- ユーザー管理は純粋関数（コマンドリスト生成）と Docker 実行（副作用）を分離する設計がテスト容易性を高める
- `user_manager.py`: 純粋関数 → ユニットテスト容易
- `service.py`: Docker exec 実行 → 統合テスト/モックテスト
- `_execute_via_file()`: ヒアドキュメント → ファイル → 実行 → クリーンアップ パターンでシェルインジェクション防止

### 改名の原則
- パッケージ名変更は段階的に: (1) ファイルシステム (mv), (2) Pythonインポート (sed), (3) 文字列リテラル (fixer並列)
- 並列fixerで効率的だが、同一ファイルの競合に注意（今回は競合なし）
- テストの env var 文字列は grep から漏れやすいので別途 sed で対応

## SillyTavern + ComfyUI + Irodori-TTS 調査 (2026-07-01)

### SillyTavern (AGPL-3.0 → 設計思想のみ採用)
- Dynamic Temperature はトークン分布ベースで感情ベースではない。Nous は emotion_decay と組み合わせ独自実装
- Persona Card V2/V3 (PNG tEXt ccv3 chunk) → import/export に最適
- Lorebook: keyword-trigger 記憶注入は Qdrant 既存で二重管理 → 過剰設計
- Expression sprites (28 GoEmotions) は過剰。Nous の感情アイコンで十分

### ComfyUI (GPL-3.0, ローカル画像生成)
- ghcr.io/clsferguson/comfyui-docker:latest が最も信頼できる
- Animagine XL 4.0 (SDXL): 日本語キャラ名直接プロンプト可
- comfy-api-simplified (MCPサーバ同梱) → Nous 統合に理想的
- A1111 は deprecated (wiki 2023-09-09 以降未更新) → StabilityProvider は将来 deprecate 必要
- 8GB VRAM 推奨、4GB でも SD1.5 ベースで動作可能

### Irodori-TTS (MIT, 日本語特化音声)
- Flow Matching + DiT (VITS 系ではない)。50,000時間日本語学習
- OpenAI TTS API 完全互換 → Nous 側は極薄ラッパー
- 感情制御: 絵文字 + キャプション + 参照音声 (3系統)
- timbre 0.9745 (6モデル中最高)、MOS 4.37
- 弱点: 開発者1名/4ヶ月、漢字読み精度、20-30秒チャンク制限

### Oracle 設計判断
- コスト制御レイヤーが決定的に不足 → PortraitGenerationConfig (デフォルトOFF) が必須前提
- DynaTemp: InferenceStep ではなく pipeline orchestrator が事前計算すべき (純粋性維持)
- D1 Lorebook: Qdrant上位互換のため Phase E 降格

### 教訓
- 「未使用コード」調査は grep では不十分。AST 検索 + データフロー追跡が必要 (RerankerModel の例)
- AI 画像生成は「デフォルトOFF」が鉄則。ユーザーが意図せず API コスト負担するリスク大
- Irodori-TTS のような若すぎるプロジェクトは「疎結合 + 別コンテナ」でリスク限定

## Group 1 実装教訓 (2026-07-01)

### Dynamic Temperature
- `emotion_temperature_scale` は `[0.0, 1.0]` にクランプ必須（実装済み: `_clamp_emotion_temperature_scale`）
- `ChatConfig` に追加したことで、既存のシリアライゼーション (`to_sql_row` / `from_sql_row`) のカラムインデックス更新を忘れがち → v032 マイグレーションで対応
- SQLite の `INTEGER` 型で `bool` を保存する際、`bool(row[44])` は `0`/`1` 以外の値も `True` と評価される可能性 → `bool(row[44] if row[44] is not None else 0)` でガード

### Persona Portrait
- `PortraitGenerationConfig` は **デフォルトOFFが絶対条件**。ユーザーが意図せずAPIコストを負担するリスクを回避
- ComfyUI は別コンテナ/別マシンが前提（GPU必須）。Nous 側は URL 設定のみで疎結合
- `auto_generate` + `emotion_threshold` の組み合わせで頻繁な再生成を防止。`generate_interval_min` + `max_monthly_budget` で二重のレート制限

### Author's Note
- `context_state` テーブルに `author_note` / `author_note_frequency` カラム追加 (v031)
- 既存の `persona_state` アクセスパターンと異なり、`update_state()` でキー・バリュー形式で書き込む（persona_info 経由ではない）
- `prompt.py` の `build_system_prompt()` で `getattr(turn_ctx, "author_note", None)` により `None` と空文字を区別（空文字/None の場合は注入しない）
- `author_note_frequency` の3モード (`always` / `every_n` / `on_emotion_change`) は現状 `always` のみ完全実装。他モードは将来拡張

### Voice (Irodori-TTS)
- `IrodoriConfig` は `Settings` にネスト設定。環境変数は `NOUS__IRODORI__*` 形式
- デフォルトOFF必須（GPUサーバー依存のため）
- OpenAI TTS API 互換なので、Nous 側のラッパーは極薄でOK
- 20-30秒チャンク制限あり。長文は分割して逐次送信する必要あり
- CPU フォールバックは非実用的（Flow Matching DiT が重い）。CPU環境では VOICEVOX が現実的代替

### 全般
- これらの機能は「MCP ツールとして新規追加」ではなく「既存設定・パイプラインの拡張」として実装
- `chat_config.py` / `settings.py` / `persona_state` の3層に分散。ドキュメントは設定変数名を追跡するのが困難
- 環境変数による設定変更は WebUI の設定画面からも行えるため、`runtime_config.py` の `hot_reload` 対応が UX 上重要

## デプロイ判断 (2026-07-01)

### ComfyUI & Irodori-TTS: 外部サービス前提
- 両方とも **GPU 必須の重いワークロード** → Nous 本体 (CPU only でOK) とは別マシン推奨
- Nous 側は HTTP URL 設定 (`comfyui_url`, `irodori_url`) だけで接続。非起動時は機能をフォールバック（エラー停止しない）
- Synology NAS (24GB RAM) に Irodori-TTS は **非推奨**: GPU がないため CPU 推論のみになり、Flow Matching (32-step DiT) で 20秒音声に1分以上。チャット対話には非実用的。軽量 TTS が欲しいなら VOICEVOX (CPU, リアルタイム) が現実的

## TE02: VoiceEngine 抽象 + IrodoriTTS 実装 (2026-07-06)
- `nous/infrastructure/voice/` 新設: `base.py` (ABC), `irodori.py` (httpx), `emotion.py` (caption + emoji), `factory.py`
- `IrodoriEngine`: POST `{url}/audio/speech` に OpenAI互換ペイロード、emotion→speedマッピング、接続エラー時2回リトライ
- `build_caption()`: `getattr(persona, "context_note", None)` で将来の PersonaState 拡張に追従可能な柔軟設計
- `EMOTION_EMOJI`: 11感情分の定数マッピング定義
- `get_voice_engine()`: `IrodoriConfig.enabled` が False の場合は None を返す
- httpx.AsyncClient モック: `mock_cls.return_value.__aenter__.return_value = mock_client` が必要（async context manager）
- テスト26件: 全pass / ruff 0 errors
- TE02f (漢字→ひらがな), TE02g (チャンク分割) はスキップ

## Minimal B: チャットメッセージツリー構造移行 (2026-07-20)

### 問題の根本原因
フラット配列 + 整数インデックスベース操作が全バグの根源:
1. 編集→即ロールバックで編集内容消失（編集したメッセージ自身もロールバックで削除）
2. DOMインデックスとサーバーインデックス乖離（querySelectorAllで割当→再採番なし）
3. segments 編集不可（update_messageがcontentのみ更新）
4. 同時編集競合（OrderedDict + INSERT OR REPLACE）

### 外部調査の学び (OpenWebUI / LibreChat)
- 両者とも parentId adjacency list（ツリー構造）を採用
- 編集 = ブランチ分岐（元メッセージ破壊しない）
- 削除 = リペアレンティング（子を孤児にしない）
- 現在位置 = リーフポインタ
- OpenWebUI: デュアルライト（JSON blob + テーブル）だが同期問題あり
- LibreChat: フラットリスト + クライアントサイド tree構築、個別削除機能は最近まで未実装

### Minimal B 設計判断
- 編集のみインプレース上書き（Minimal），ロールバックは active_leaf_id 差し替えのみ（非破壊）
- 3-6ヶ月後に編集のブランチ分岐へアップグレード可能（データモデル変更不要）
- UUID生成は uuid.uuid4()（uuid7 は pip install 制限により断念）
- 後方互換: from_db() で旧フラット配列を検出 → 自動マイグレーション

### 注意点
- TreeSessionWindow は SessionWindow と一時的に並存（全移行完了後に削除）
- post.py の episode_consolidation（L88）が session._messages 直参照 → TreeSessionWindow 移行時に要修正
- DoneSSE に user_msg_id / assistant_msg_id 追加でフロントエンドとメッセージID同期
