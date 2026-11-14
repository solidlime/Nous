# MCP Server Capabilities Research (2026-06-27)

MemoryMCPの5機能領域について、関連MCPサーバー実装35+件を調査した結果をまとめる。
各セクションは「プロジェクト → URL → キーパターン → MemoryMCPへの教訓」形式。

---

## 1. 画像生成 in MCP Servers

### 主要プロジェクト

#### pvliesdonk/image-generation-mcp
- **URL**: https://github.com/pvliesdonk/image-generation-mcp
- **対応プロバイダー**: OpenAI (gpt-image-1.5/1, dall-e-3), Google Gemini (gemini-2.5-flash-image), SD WebUI, Placeholder
- **キーパターン**:
  - **Capability Discovery Protocol**: 各プロバイダーの `discover_capabilities()` が起動時にアスペクト比・品質・フォーマット・negative-promptサポートを返却。ルーティングは enum ではなく capability サーフェスに問い合わせる
  - **Per-model `style_profile` メタデータ** + 統一 `warnings[]` 配列
  - **Pyproject extras**: `mcp` (fastmcp[tasks]) / `openai` / `google-genai` / `all` — オプショナル依存
  - **環境変数命名**: `IMAGE_GENERATION_MCP_<PROVIDER>_<FIELD>` — プレフィックスで名前空間化
  - **デフォルトルーター**: `IMAGE_GENERATION_MCP_DEFAULT_PROVIDER=auto` — 設定キー1つで切替
  - **Read-only mode**: `IMAGE_GENERATION_MCP_READ_ONLY=true` で書き込みツール非表示
- **教訓**:
  1. Capability protocol は新プロバイダーの追加コストを最小化する（router edits 不要）
  2. 環境変数プレフィックス + セクション区切り (`<PROVIDER>_<FIELD>`) は将来の拡張に強い
  3. 起動時の capability キャッシュで毎回APIを叩かない

#### thebenlamm/image-gen-mcp
- **URL**: https://github.com/thebenlamm/image-gen-mcp
- **対応**: 8プロバイダー (OpenAI, Gemini, Replicate, Together, xAI Grok, Photoroom, fal.ai, Ideogram) — 7ツール
- **キーパターン**:
  - **Capability-based routing**: `list_capabilities` ツールが全6プロバイダーの cost/latency メタデータを返却 → `image_task` がそれで判断
  - **Eval-populated `quality.scores`**: プロバイダー間品質スコアを内部評価で蓄積しルーティングに使用
  - **Capability-only providers**: Photoroom/fal/Ideogram は `image_op` 経由でのみ露出（generateは不可）
- **教訓**: 品質のメタデータを事前評価で持つアプローチは評価コストと引き換えに最適ルーティングを実現

#### superjavason/imagegen-mcp
- **URL**: https://github.com/superjavason/imagegen-mcp
- **対応**: OpenAI (DALL-E 2/3, GPT-Image-1), Stability, Replicate, Hugging Face
- **キーパターン**:
  - **Unified MCP tools**: プロバイダー非依存の `text-to-image` / image edit ツール
  - **CLI引数でprovider選択**: `--providers openai stability` / `--models dall-e-3 stable-diffusion-xl-1024-v1-0`
- **教訓**: CLIのprovider/modelセレクタ方式は環境変数だけだと操作しづらい

#### Ozymandros/image-gen-mcp
- **URL**: https://github.com/Ozymandros/image-gen-mcp
- **対応**: Stability AI + Gemini Imagen — **2プロバイダー**
- **キーパターン**:
  - **Hexagonal Architecture**: `ImageGen.Domain/ Application/ Infrastructure/ McpHost/ Tests/ Documentation/` の6レイヤー
  - **Fail-fast startup**: 設定検証は接続受付前に完全実施
  - **Polly resilience**: 5xx/429 に自動リトライ + jitter
  - **FluentValidation**: prompt length/aspect ratio/step range を HTTP 呼び出し前に検証
  - **stderr分離**: stdout は JSON-RPC 専用、ログは stderr
  - **Adding new provider = 4 steps**, Infrastructure layer のみ変更
- **教訓**:
  1. **Hexagonal + Interface実装だけ**で新プロバイダーを追加できる設計は保守コスト最小
  2. 起動時 fail-fast は「動かないこと」より「動かなくなる前に知らせること」を優先する姿勢
  3. stderr分離はMCPプロトコルの正規作法

#### ptbsare/imagegen-mcp-server
- **URL**: https://github.com/ptbsare/imagegen-mcp-server
- **対応**: OpenAI互換 + Gemini
- **キーパターン**:
  - **Async/Sync両対応**: `submit_task` + `get_task` (非ブロッキング) と `generate_image` (同期)
  - **`IMAGEGEN_ASYNC_ONLY` フラグ**: 遅いプロバイダーは非同期のみ公開可能
  - **常にbase64 MCP ImageContent返却**: 一時ファイルを作らない
  - **`OPENAI_BASE_URL` / `GEMINI_BASE_URL`**: カスタムAPIプロキシ対応
  - **3トランスポート**: stdio / SSE / HTTP
  - **Auto-loads `.env`** + CLI引数
- **教訓**:
  1. 同期/非同期の切替は実運用上重要（タイムアウト回避）
  2. `BASE_URL` 対応は OpenRouter/Azure 等への布石として必須
  3. 常にbase64 = 一時ファイルを作らずステートレス。再現性 ◎

#### marc-shade/image-gen-mcp
- **URL**: https://github.com/marc-shade/image-gen-mcp
- **対応**: 5プロバイダー (Pollinations無料デフォルト, Cloudflare, Together, HF, Replicate)
- **キーパターン**:
  - **FREE default**: Pollinations.ai はAPIキー不要で即動作
  - **自動フォールバックチェーン**: 1→2→3→4→5 まで全滅で全試行ログ返却
- **教訓**: フォールバック設計は可用性を劇的に上げるが、トークン消費とレイテンシとのトレードオフ

### 画像返却フォーマットの標準パターン

| パターン | 採用プロジェクト | 長所 | 短所 |
|---|---|---|---|
| **base64 MCP ImageContent** | ptbsare, simonChoi034, krystian-ai | ステートレス、LLMが直接参照可 | サイズ大、トークン消費 |
| **file path + metadata** | pvliesdonk, Noi1r/pdf-mcp | キャッシュ可能、再利用可能 | パス管理必要 |
| **URL（CDN/署名付き）** | 計画中（krystian-ai v0.2） | 共有可能、軽量 | 有効期限管理 |
| **画像保存 → text URL返却** | superjavason | シンプル | クライアントが読まないと見えない |

**結論**: MCP仕様ではbase64の `ImageContent` が最も一般的。**MemoryMCPは OpenAI互換の `[{type:text}, {type:image_url}]` を採用済み**（MEMORY.md 2026-06-08 記載）→ これは既に標準準拠。

### MemoryMCPへの教訓（画像生成）

1. **Capability Discovery Pattern** を採用すると、将来のプロバイダー追加が容易
2. **Hexagonal Architecture** で新プロバイダーは Infrastructure 層のみ触る
3. **環境変数プレフィックス命名規則** (`MEMORY_MCP_<FEATURE>_<KEY>`) は既存パターンと整合
4. **stderr分離 + 起動時fail-fast + FluentValidation** の三点は MCP サーバー実装の定石

---

## 2. PDF Reading in MCP Servers

### 主要プロジェクト

#### rsp2k/mcp-pdf（最も包括的）
- **URL**: https://github.com/rsp2k/mcp-pdf
- **ライブラリ構成**:
  - **テキスト抽出**: PyMuPDF → pdfplumber → pypdf の**自動フォールバック**
  - **テーブル抽出**: Camelot → pdfplumber → Tabula の**自動フォールバック**
  - **OCR**: Tesseract
  - **ベクター抽出**: SVGエクスポート
  - **PDF↔Markdown**: PyMuPDF + pandoc
  - **XFA Forms**: Adobe LiveCycle対応
- **49ツール**, **オプショナルextras** (`[forms]`, `[tables]`, `[markdown]`, `[all]`)
- **必須システム依存**:
  - `tesseract-ocr` (OCR)
  - `ghostscript` (Camelot)
  - `default-jre-headless` (Tabula)
  - `poppler-utils` (PDF→image)
  - `pandoc` + LaTeX (`markdown_to_pdf`)
- **キーパターン**:
  - **自動ライブラリフォールバック**: 1つ失敗 → 2つ目 → 3つ目を試行
  - **Pyproject extras**: 重い依存を必要に応じてオプショナル化
  - **Large file handling**: ページチャンクで分割処理
- **教訓**:
  1. **フォールバック連鎖は本番品質の要** — PyMuPDF は高速だが複雑なレイアウトは pdfplumber が強い
  2. OCR は Tesseract + 言語パック（`eng+fra+deu+spa` 等）の組み合わせ
  3. テーブル抽出は Camelot (Ghostscript依存) が最高精度だが重く、pdfplumber がフォールバック

#### nfsarch33/pdf-mcp-server（最も機能豊富）
- **URL**: https://github.com/nfsarch33/pdf-mcp-server
- **特徴**: 56ツール、CLI + MCP両対応
- **ライブラリ**: `pypdf` (BSD), `fillpdf` (MIT), `pymupdf` (AGPL-3.0)
- **キーパターン**:
  - **Engine selection**: "native" / "auto" / "smart" / "ocr" / "force_ocr"
  - **`detect_pdf_type`**: "searchable" / "image_based" / "hybrid" を自動分類
  - **`include_confidence=True`**: 単語レベル信頼度スコア
  - **テキストブロック + bounding box**: フォームフィールド検出用
  - **フォーム処理**: AcroForm + label-detection fallback
  - **OCR languages**: Tesseract + 言語パック（インストール状態も `get_ocr_languages` で確認可能）
  - **PII検出**: `detect_pii_patterns` で秘匿情報検出
  - **PDF署名**: PKCS#12/PEM対応
  - **バッチ処理**: `batch-process` / `compare-pdfs`
- **教訓**:
  1. エンジンの明示的選択（`auto` / `force_ocr`）はLLMにとって使いやすい
  2. `detect_pdf_type` を前段で噛ませると OCR 判定ミスが減る
  3. PII検出は個人情報保護の要件次第で必須

#### damateosg/pdf-reader-mcp（最小実装の模範）
- **URL**: https://github.com/damateosg/pdf-reader-mcp
- **ライブラリ**: PyMuPDF + Tesseract
- **5ツール**: `read_pdf_text` / `read_pdf_ocr` / `read_pdf_smart` / `pdf_info` / `ocr_status`
- **キーパターン**:
  - **`read_pdf_smart` の判定閾値**: ページテキスト ≥ 30文字 → native、< 30文字 → OCR fallback
  - **モジュール分離**: `pdf_utils.py` は MCP 非依存、CLIからも再利用可能
  - **OCR availability check**: `ocr_status` で Tesseract のインストール状態と言語を返す
- **教訓**:
  1. **30文字閾値**は経験的に妥当な「OCR必要か」の境界値
  2. **コアロジックを MCP非依存に分離** → テスト・CLI利用・別サーバー移植が容易
  3. **段階的graceful degradation**: Tesseract無くてもテキストPDFは読める

#### Noi1r/pdf-mcp（キャッシュ戦略の模範）
- **URL**: https://github.com/Noi1r/pdf-mcp
- **ライブラリ**: PyMuPDF + SQLite キャッシュ
- **キーパターン**:
  - **SQLiteキャッシュ**: `~/.cache/pdf-mcp/cache.db` にメタデータ・ページテキスト・画像パスを保存
  - **キャッシュされる内容**: メタデータ・ページ単位テキスト・画像パス（base64ではない）
  - **自動無効化**: ファイル変更検知で invalidation
  - **`pdf_cache_stats` / `pdf_cache_clear`**: キャッシュ管理ツール
  - **画像返却**: file path のみ（base64ではない）
  - **`tempfile.mkdtemp()` フォールバック**: `output_dir` 未指定時
- **教訓**:
  1. **大きなPDFはキャッシュ必須** — 毎回全文パースすると遅い
  2. 画像は base64 より **file path の方が軽量・再利用可能**
  3. キャッシュ無効化はファイル更新時刻で自動化可能

#### labeveryday/mcp_pdf_reader（FastMCP標準準拠）
- **URL**: https://github.com/labeveryday/mcp_pdf_reader
- **ライブラリ**: FastMCP + PyMuPDF + pytesseract + Pillow
- **5ツール**: テキスト・画像・OCR・メタデータ・構造解析
- **キーパターン**: FastMCP で `@mcp.tool` を使う標準的な実装、 `ocr_language` パラメータ
- **教訓**: 日本語PDF対応なら `tesseract-ocr-jpn` パッケージの追加が必要

### MemoryMCPへの教訓（PDF）

1. **ライブラリフォールバック戦略**:
   - テキスト: PyMuPDF → pdfplumber → pypdf
   - テーブル: Camelot → pdfplumber → Tabula
   - 画像: pdf2image (poppler)
2. **必須システム依存**を Dockerfile に明示:
   ```
   tesseract-ocr tesseract-ocr-jpn tesseract-ocr-eng
   ghostscript default-jre-headless
   poppler-utils pandoc
   ```
3. **キャッシュはSQLite**で page単位 / 画像 path保存 — 既にMemoryMCPは SQLite ベースなので相性 ◎
4. **`detect_pdf_type` + `read_pdf_smart` の二段戦略**がLLMに最も扱いやすい
5. **コアロジックはMCP非依存の `pdf_utils.py`** に分離（テスト容易性）
6. **30文字閾値**でOCR判定

---

## 3. Skills/Plugins in MCP Servers

### Agent Skills 標準仕様

#### agentskills.io
- **URL**: https://agentskills.io/specification
- **形式**: `SKILL.md` ファイル + YAML フロントマター
- **ディレクトリ構造**:
  ```
  my-skill/
  ├── SKILL.md          # 必須
  ├── scripts/          # 実行可能コード
  ├── references/       # 追加ドキュメント
  ├── assets/           # テンプレート・画像
  ```
- **フロントマター仕様**:
  | Field | Required | Constraints |
  |---|---|---|
  | `name` | Yes | 1-64文字、a-z0-9-、親ディレクトリ名と一致 |
  | `description` | Yes | 1-1024文字、XML禁止、何をするかといつ使うかを記述 |
  | `license` | No | ライセンス名 |
  | `compatibility` | No | 1-500文字、環境要件 |
  | `metadata` | No | 任意の KV |
  | `allowed-tools` | No | スペース区切り、Experimental |
- **Progressive Disclosure（3段階）**:
  1. 起動時: name + description のみ (~100 tokens)
  2. アクティブ時: SKILL.md 全体 (< 5000 tokens 推奨)
  3. 必要に応じて: `scripts/` `references/` `assets/`
- **教訓**:
  1. `SKILL.md` 形式は既に**業界標準** — MemoryMCPのプラグイン機構もこれに準拠すべき
  2. Progressive Disclosure は**コンテキスト消費を最小化**する鍵

#### anthropics/skills（公式リファレンス）
- **URL**: https://github.com/anthropics/skills
- **構造**: `./skills` (例) + `./spec` (仕様) + `./template` (雛形)
- **マーケットプレース**: `/plugin marketplace add anthropics/skills` でインストール可能
- **`agentskills.io`** が仕様の正典

#### 公式ブログ「Equipping agents for the real world with Agent Skills」
- **URL**: https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- **キーパターン**:
  - **Progressive Disclosure の3レベル**:
    1. メタデータ
    2. SKILL.md 全体
    3. 参照ファイル
  - **Bundled scripts**: コード実行で出力を得る（スクリプト自体はコンテキストに乗らない）
  - **`SKILL.md` < 5000 tokens 推奨**
- **教訓**: スキルは「フォルダ単位」でコンテキストを節約する設計

### Skills の動的読み込みパターン

#### Code execution with MCP（Anthropic 2025-11-04）
- **URL**: https://www.anthropic.com/engineering/code-execution-with-mcp
- **キーパターン**:
  - **MCP servers as code APIs**: 直接 tool call ではなく、ファイルシステム探索でツール定義を読む
  - **トークン削減**: 150,000 tokens → 2,000 tokens（**98.7% 削減**）
  - **`search_tools` ツール**: 関連ツールのみをオンデマンドで取得
  - **`detail level` パラメータ**: name のみ / name+description / full schema
  - **State persistence**: 中間結果をファイル保存、再開可能
  - **Skills = 保存された関数群**: スキルは「再利用可能なコードの集大成」
- **教訓**:
  1. **Skills 経由で MCP ツールを呼ぶ**とコンテキスト消費が激減する
  2. **`search_tools` パターン**はツール数が増えたときの解決策

#### claude-code Issue #21545: Lazy-load skills
- **URL**: https://github.com/anthropics/claude-code/issues/21545
- **問題**: 全MCPツールの full schema が起動時にロードされコンテキストの 30-40% を消費
- **提案**:
  1. 起動時は name のみロード
  2. 必要時に full schema をロード
  3. **`/mcp add linear` で mid-session enable** — `mcp__plugin_...__...` 形式
- **教訓**: プラグイン多数時の**lazy-loading は必須要件**

#### claude-code Issue #61513: `/.well-known/agent-skills` 発見
- **URL**: https://github.com/anthropics/claude-code/issues/61513
- **パターン**: Cloudflare の `agent-skills-discovery-rfc` 準拠
  ```
  GET /.well-known/agent-skills/index.json
  ```
- **検証**: `$schema` + digest
- **教訓**:
  1. リモートスキル発見の**業界標準化**が進んでいる
  2. スキル提供側が `SKILL.md` を直接配信する形が想定されている

### Skills/Plugins MCP実装例

#### helmforgedev/fastmcp-server（動的ローディングの実装例）
- **URL**: https://github.com/helmforgedev/fastmcp-server
- **キーパターン**:
  - **動的コンポーネント読み込み**: 起動時に workspace ディレクトリから tools/resources/prompts/knowledge をスキャン
  - **Sources**: Inline / S3 / Git から sync
  - **Web UI at `/ui`**: ダッシュボード、Tools Explorer、Prompts Explorer（15秒ごと自動リフレッシュ）
  - **`MCP_UI_ENABLED=false`**: UI オフ可能
  - **`EXTRA_PIP_PACKAGES`**: 起動時に pip install
- **教訓**:
  1. **workspace ディレクトリスキャン**でプラグインを追加するパターンは MemoryMCPの `plugins/` 構成と非常に親和性が高い
  2. UI 自動リフレッシュは便利だがバッテリー/帯域を食うので off 可能に

#### Anthropic Plugin マーケットプレース
- **`/plugin marketplace add anthropics/skills`**: マーケットプレース形式でインストール
- **`${CLAUDE_PLUGIN_ROOT}`**: プラグインディレクトリの参照
- **`.mcp.json`**: プラグイン毎に MCP 設定
- **Bundle MCP server with plugin**: 自動セットアップ
- **Tool Discovery 3状態**: `registerTool` で全MCPプリミティブ統合

### MemoryMCPへの教訓（Skills/Plugins）

1. **`SKILL.md` 標準**を採用する（フロントマター `name` + `description` 必須）
2. **Progressive Disclosure**: プラグイン一覧では name/description のみ、フルロードはオンデマンド
3. **`plugins/` ディレクトリスキャン**方式は既に着手済み（MEMORY.md に従う）
4. **`/well-known/agent-skills/index.json`** での外部公開も将来検討
5. **スキーマレベルでの `search_tools`** を提供すると将来的にツール数が増えても破綻しない
6. **`allowed-tools` フィールド**（Experimental）: スキルが使って良いツールを制限

---

## 4. Memory/Persistence in MCP Servers

### 公式ベース実装

#### modelcontextprotocol/servers/src/memory
- **URL**: https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md
- **実装**: JSONL knowledge graph（後発の多数が SQLite に置換）
- **エンティティ/関係/観測の3要素**:
  - `Entity { name, entityType, observations[] }`
  - `Relation { from, to, relationType }` (active voice)
  - 観測は atomic (1 fact per observation)
- **基本ツール**: `create_entities` / `create_relations` / `add_observations` / `delete_*` / `read_graph` / `search_nodes` / `open_nodes`
- **MCP Resource**: `memory://knowledge-graph` — JSON で全グラフ公開
- **Notifications**: mutation 時に `notifications/resources/updated` 発火 → 購読クライアントがライブ更新受信
- **教訓**:
  1. **Resource** として全グラフ公開 + `notifications/resources/updated` で push 更新は標準パターン
  2. JSONL は並行アクセスで corruption するため、SQLite への移行が業界トレンド

### SQLite + Vector 系（ドロップイン置換）

#### Yarlan1503/mcp-memory（公式の SQLite 置換）
- **URL**: https://github.com/Yarlan1503/mcp-memory
- **スタック**: SQLite (WAL) + sqlite-vec + ONNX embeddings (94+ 言語) + FastMCP
- **キーパターン**:
  - **WAL + 5秒 busy_timeout + CASCADE delete**
  - **Singleton ONNX model** を起動時に一度だけロード
  - **Limbic Scoring**: re-ranking with importance signals, temporal decay, co-occurrence patterns, RRF scores
  - **semantic + FTS5 hybrid search** (RRF merge)
  - **Semantic deduplication**: `similarity_flag` on cosine >= 0.85
  - **Containment fix**: テキスト長比 ≥ 2.0 の非対称テキスト対応
  - **KNN + FTS5 を並列実行**:
    1. KNN (vector)
    2. FTS5 (BM25)
    3. RRF でマージ
- **教訓**:
  1. **WAL + busy_timeout** は MCP サーバー（並行クライアント）の最低条件
  2. **KNN + FTS5 + RRF** は事実上の標準ハイブリッド検索
  3. **Deduplication は cosine + containment** の二段

#### dustinspace217/mcp-memory-server（時系列 + 退避チェイン）
- **URL**: https://github.com/dustinspace217/mcp-memory-server
- **4-tier lifecycle**:
  - **Active** → 通常のクエリ対象
  - **Superseded** → 非表示だが履歴保持
  - **Tombstoned** → 内容は消去、存在のみ保持
  - **Hard-deleted** → 完全に削除
- **6-month LRU shield** + デフォルト1GB サイズ上限
- **Temporal versioning**: `as_of` パラメータで過去時点のグラフ状態を復元
- **`entity_timeline`**: 全階層の履歴を一覧
- **エンティティ名正規化**: 大文字小文字・区切り文字を無視した一致
- **JSONL → SQLite 自動マイグレーション**
- **`MEMORY_VECTOR_SEARCH=off`**: ベクトル検索を無効化可能
- **教訓**:
  1. **4-tier lifecycle** は MemoryMCP の Ebbinghaus 曲線と非常に親和性が高い
  2. **`as_of` パラメータ**は監査・ロールバックに必須級
  3. サイズ上限 + LRU shield は長期運用に必須

#### bripin123/rag-memory-epf-mcp（多言語 + グラフ + 31ツール）
- **URL**: https://github.com/bripin123/rag-memory-epf-mcp
- **31 MCPツール**: knowledge graph CRUD + document pipeline + hybrid search + multi-hop traversal + graph analytics
- **キーパターン**:
  - **codepoint-safe chunking** for Korean/CJK/emoji
  - **`better-sqlite3 12.x` + `sqlite-vec 0.1.7` + FTS5 triggers + 7 indexes**
  - **WAL + 32MB cache + 256MB mmap + busy_timeout**
  - **Reciprocal Rank Fusion** for vector + FTS5 + graph 3-signal
  - **3-signal hybrid search**: vector + FTS5 BM25 + graph traversal
  - **`search_mode` で FTS5-only degrade** フォールバック
  - **temporal filtering**: `since` / `until` ISO 8601
  - **Entity upsert**: 新規観測を既存エンティティにマージ
  - **Dedup by content**: 日付除去後の比較で重複防止
- **教訓**:
  1. **CJK/絵文字対応の chunking** は日本語特化の MemoryMCP で既に意識すべき
  2. **3-signal hybrid** は最高品質だが複雑、MemoryMCP は RRF 2-signal でも十分
  3. **embedding model down 時の graceful degradation** は必須

#### memora-mcp（LLM dedup + グラフ + チャットの統合）
- **URL**: https://github.com/memora-mcp  / PyPI `memora-mcp`
- **キーパターン**:
  - **SQLite + 任意クラウド同期** (S3, R2, D1)
  - **Hierarchical Organization**: section/subsection 自動階層
  - **Export/Import**: バックアップ + マージ戦略
  - **TF-IDF / sentence-transformers / OpenAI** の embedding バックエンド切替
  - **Tag filters AND/OR/NOT**
  - **Auto-linked related memories** (cross-references)
  - **LLM Deduplication**: `memory_find_duplicates` + `memory_merge` (append/prepend/replace)
  - **LLM Comparison の出力**:
    - `verdict`: "duplicate" / "similar" / "different"
    - `confidence`: 0.0-1.0
    - `reasoning`: 説明
    - `suggested_action`: "merge" / "keep_both" / "review"
- **教訓**:
  1. **LLM による意味的 dedup** は cosine 閾値より高精度だが、API コスト・レイテンシと引き換え
  2. **3戦略 (append/prepend/replace)** のマージは実用的
  3. **Section/subsection 階層**は MemoryMCP のナレッジ整理にも応用可能

#### nwxio/mcp-memory（OmniMemory — フル機能）
- **URL**: https://github.com/nwxio/OmniMemory
- **特徴**: 構造化メモリ + セマンティック検索 + KG + 自動抽出 + ライフサイクル
- **メモリ種別**: lessons / preferences / procedures / entities / relations
- **バックエンド**: SQLite (default) + PostgreSQL + Redis (cache) + Neo4j (graph)
- **Embedding**: fastembed (local) / OpenAI / Cohere
- **Lifecycle**: cleanup / decay / TTL / prune consolidation
- **キーパターン**:
  - **Auto-extraction pipeline** for facts/events/preferences/relations/rules/skills
  - **Procedural memory** (how-to steps) — スキルとの相性 ◎
  - **Cross-session context injection** 自動化
- **教訓**:
  1. **Procedural memory** は MemoryMCP のスキル機構と統合可能
  2. **Auto-extraction** は LLM コストとのバランスで「ルール」で制御
  3. **複数バックエンド対応**はエンタープライズ導入で必要

#### PhillipAWells/mcp-memory（OpenAI embedding + Hybrid RRF）
- **URL**: https://github.com/PhillipAWells/mcp-memory
- **スタック**: OpenAI embeddings + Qdrant + hybrid search (RRF)
- **キーパターン**:
  - **Reciprocal Rank Fusion** (RRF) による dense + keyword 統合
  - **自動 expiry**: episodic 90日、short-term 7日
  - **Workspace isolation** マルチワークスペース
  - **Secrets detection** — 機密情報（API キー等）の保存防止
  - **Dual embeddings**: small + large の2種類埋め込み
  - **Embedding cache** (LRU + usage tracking)
  - **Confidence score filter** + **tag filter**
- **教訓**:
  1. **期限ベースの自動失効** は MemoryMCP の忘却曲線に組み込み可能
  2. **Secrets detection** は MemoryMCP の `_REDACT_PATTERNS` のような仕組みで既に対応済み

### Qdrant ベース

#### qdrant/mcp-server-qdrant（公式）
- **URL**: https://github.com/qdrant/mcp-server-qdrant
- **基本ツール**: `qdrant-store` + `qdrant-find` の2つだけ
- **キーパターン**:
  - **`TOOL_STORE_DESCRIPTION` / `TOOL_FIND_DESCRIPTION`** 環境変数でツール説明文を**カスタム化** → LLMの使い方を誘導
  - **`QDRANT_READ_ONLY`**: 書き込み無効化
  - **`COLLECTION_NAME`**: デフォルトコレクション名（必須化を回避）
  - **PR #20**: メタデータフィルタリング + 関連度スコア返却
  - **PR #95（mrkutin 分岐）**: **BM25 sparse vectors + RRF** によるハイブリッド検索
  - **`project` パラメータ**で全データに自動タグ付け + payload index
- **教訓**:
  1. **ツール説明文のカスタマイズ**環境変数は LLM パフォーマンスに直結
  2. **プロジェクトタグ**でマルチプロジェクト対応
  3. RRF は Qdrant でも業界標準

#### hannesnortje/MCP（ガバナンス統合型）
- **URL**: https://github.com/hannesnortje/MCP
- **75ルール + セマンティックポリシー検索 + SHA-256 整合性検証**
- **9 MCPツール + 4 MCP Resources**
- **教訓**: MemoryMCP にも policy / rule 層を追加するとガバナンス強化

#### Ruben-Alvarez-Dev/MCP-agent-memory（L0-L5 階層型）
- **URL**: https://github.com/Ruben-Alvarez-Dev/MCP-sgent-memory
- **6層構造**:
  - L0 RAW: append-only event lake (JSONL)
  - L1 WORKING: steps, facts, hot dialogue (Qdrant)
  - L2 EPISODIC: grouped events, incidents (Qdrant + SQLite)
  - L3 SEMANTIC: decisions, entities, patterns
  - L4 CONSOLIDATED: narratives, deep summaries
  - L5 SELECTIVE: context routing and assembly
- **Auto consolidation**: `L0_to_L4_consolidation_heartbeat` / `_consolidate` / `_dream`
- **Dream cycle** (background pattern detection)
- **Memory type**: L3 facts (semantic CRUD), L2 conversations, L0 events
- **教訓**:
  1. **L0-L5 階層**は MemoryMCP の忘却曲線と統合可能（active=高層、decay=低層）
  2. **Dream cycle** でバックグラウンド統合は面白い
  3. ただしオーバーキル感も否めない

### 忘却曲線 / 減衰系

#### Kore Memory（Ebbinghaus + 自動スコアリング）
- **URL**: https://github.com/auriti-web-design/kore-memory
- **キーパターン**:
  - **5段階 importance** + half-life (1=7日, 2=14日, 3=30日, 4=90日, 5=365日)
  - **decay = e^(−t · ln2 / half_life)**
  - **検索時 retrieval で +15% ブースト** (spaced repetition)
  - **Ranking profile**: "default" / "coding"
  - **スコア分解** (explain=true): similarity × decay × confidence × task_relevance × graph_centrality
  - **TTL / Soft-delete / Archive**
  - **Web dashboard + Prometheus metrics**
- **教訓**:
  1. MemoryMCP の Ebbinghaus 実装と非常に近い
  2. **ranking profile 切替**（coding vs default）は LLM タスク適応に便利
  3. **explain=true** でスコア根拠を返すのは UX 改善

#### YourMemory（sachitrafa）
- **URL**: https://github.com/sachitrafa/yourmemory
- **キーパターン**:
  - **`active_days`**: ユーザーが活動した日だけカウント（休暇で記憶喪失しない）
  - **decay 0.05 未満 → 自動 prune** (24h cron)
  - **Session wrap-up**: アイドル30分で recalled memory IDs にブースト
  - **Chain-aware pruning**: グラフ隣接が高い記憶は連鎖して延命
  - **Hybrid score = 0.4×BM25 + 0.6×cosine**
  - **BM25 + vector + graph + decay** の4要素
  - **LoCoMo Recall@5 = 59%**（Mem0 = 18%, Zep = 28%, Supermemory = 31%）
- **教訓**:
  1. **active_days 概念**は実用的（ユーザーアクティブ期間のみカウント）
  2. **Chain-aware pruning** は KG を持つ MemoryMCP に組み込み可能
  3. **LoCoMo ベンチ** で Ebbinghaus の優位性が示されている

#### FSRS ベース
- **URL**: https://dev.to/zanfiel/i-replaced-exponential-decay-with-spaced-repetition-in-my-ai-memory-server-51dc
- **キーパターン**:
  - **FSRS (Free Spaced Repetition Scheduler)**: 21パラメータ power-law decay
  - **Bjork dual-strength model**: retrieval strength (power-law) + storage strength
  - **combined = 0.7 × retrieval + 0.3 × (storage/10)**
  - **`/fsrs/init` で既存メモリをバックフィル**
- **教訓**:
  1. FSRS は Anki で実証された power-law が人間の記憶に正確
  2. MemoryMCP の Ebbinghaus (exponential) より高精度の可能性
  3. ただし実装複雑度は高い

### MemoryMCPへの教訓（Memory/Persistence）

1. **4-tier lifecycle** (Active → Superseded → Tombstoned → Hard-deleted) は MemoryMCP の忘却曲線に統合すべき
2. **WAL + busy_timeout** は並行アクセス対策で必須（既に SQLite ベースで対応済）
3. **KNN + FTS5 + RRF** のハイブリッド検索が業界標準
4. **`as_of` パラメータ**で時系列クエリ対応 → MemoryMCP の audit log に活用
5. **embedding 失敗時の graceful degradation**（LIKE-only フォールバック）
6. **Tool description のカスタマイズ環境変数**（MemoryMCP は既に日本語特化でやってる）
7. **size cap + LRU shield** は長期運用で必須
8. **active_days 概念**や **chain-aware pruning** は面白い
9. **Secrets detection** は既に対応済み（MEMORY.md 参照）
10. **LLM による意味的 dedup** は高精度だがコスト高

---

## 5. Docker-first Deployment Patterns

### 標準パターン

#### mcp-compose (phildougherty)
- **URL**: https://github.com/phildougherty/mcp-compose
- **特徴**: Docker Compose for MCP + Unified API gateway
- **機能**:
  - **HTTP proxy** (STDIO → HTTP 自動変換)
  - **Docker / Podman** 両対応
  - **Session management + connection pooling**
  - **Dashboard + monitoring** 内蔵
  - **OpenAPI spec 生成**
- **YAML 構造**:
  ```yaml
  version: '1'
  proxy_auth:
    enabled: true
    api_key: "${MCP_API_KEY}"
  servers:
    filesystem:
      protocol: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
      capabilities: [resources, tools]
      volumes: ["${HOME}:${HOME}:ro"]
  ```
- **3 プロトコル**: stdio / http / sse
- **教訓**:
  1. **STDIO → HTTP 透過プロキシ** は複数クライアントから MCP サーバーを共有する現実解
  2. **`mcp-compose up` 一発で複数サーバー起動** は MemoryMCP の docker-compose.yml に既に取り入れている

#### ppiova/mcp-docker-starter（最小実装の模範）
- **URL**: https://github.com/ppiova/mcp-docker-starter
- **特徴**: Python MCP + .NET Agent client のポリグロット compose
- **キーパターン**:
  - **Service discovery by name**: `http://mcp-server:8000/mcp`
  - **Non-root containers** 両方
  - **Healthcheck on MCP server** + **client readiness wait** (`WaitForEndpointAsync`)
  - **`.env` 経由の secrets**（コミット禁止）
  - **DNS-rebinding 対策**: `TransportSecuritySettings(allowed_hosts=...)` を `MCP_ALLOWED_HOSTS` で環境変数化
  - **Multi-stage build**（.NET 側）
- **教訓**:
  1. **`WaitForEndpointAsync`** パターンは .NET 限定だが、Python でも httpx polling で実現可能
  2. **DNS-rebinding 対策**は FastMCP で既に有効だが、知っておくと安心
  3. `.env` + `.gitignore` + `.dockerignore` の3点セット

#### pedrosakuma/dotnet-native-mcp（複数サーバー連携）
- **URL**: https://github.com/pedrosakuma/dotnet-native-mcp
- **特徴**: 3サーバー (diagnostics / assembly / native) を1つの compose で起動
- **教訓**:
  1. **3ファイル同一 compose** 問題は「drift 防止」が最大の保守コスト
  2. shared environment + shared volumes + healthcheck all services

### Docker MCP Toolkit (Docker 公式)

#### Docker MCP Toolkit
- **URL**: https://docs.docker.com/ai/mcp-catalog-and-toolkit/toolkit/
- **概要**: Docker Desktop 統合の MCP サーバー管理
- **Catalog**: 300+ verified servers
- **Profile-based organization**: プロジェクト別サーバ集合
- **Dynamic MCP**: 会話中にサーバーをオンデマンドで発見・追加
- **セキュリティ**:
  - **Image signing + SBOM**: 全 `mcp/` 名前空間画像は Docker がビルド・署名
  - **CPU制限**: 1 CPU
  - **Memory制限**: 2 GB
  - **Filesystem access**: デフォルトで host FS アクセスなし
  - **Tool request interception**: 機密情報（secrets）含むリクエストをブロック
- **OAuth handling**: ブラウザ認証自動処理
- **教訓**:
  1. **2GB / 1CPU 制限** は MCP サーバーリソース設計の参考値
  2. **Filesystem デフォルト隔離** は MemoryMCP の data ボリューム設計に既に取り入れ済み
  3. **Image signing + SBOM** はエンタープライズ向け

### DinD vs DooD パターン

#### Docker ブログ "Node.js Sandbox"
- **URL**: https://www.docker.com/blog/connect-mcp-servers-to-claude-desktop-with-mcp-toolkit/
- **パターン**: **DooD (Docker-out-of-Docker) = `/var/run/docker.sock` マウント**
- **動作**:
  - サンドボックスコンテナ → Docker API で一時的 sibling コンテナ起動
  - `node:lts-slim`, `playwright` 等のイメージを使用
  - 512MB RAM / 0.75 CPU 制限
  - 自動削除 (`--rm`)
- **セキュリティ注意**:
  - **socket mount = root-level ホストアクセス権**（特権昇格ベクトル）
  - ローカル開発はOK、本番は慎重に
  - **Docker Scout での脆弱性スキャン**推奨
- **代替**: True DinD（`docker:dind` イメージ）— 隔離性高いが、volume mount不可
- **教訓**:
  1. **DooD は簡便だがセキュリティリスク高** — 信頼できるイメージのみ
  2. **sibling コンテナ + resource limit + auto-remove** は基本パターン
  3. MemoryMCP の **sandbox 機能** (MEMORY.md の `MEMORY_MCP_SANDBOX__ENABLED`) はこの文脈で重要

### 本番デプロイメントパターン

#### Stanza MCP Production Guide
- **URL**: https://www.stanza.dev/courses/mcp-production/deployment-patterns/mcp-production-infrastructure
- **キーパターン**:
  - **depends_on with `condition: service_healthy`**: 依存サービスのヘルスチェック後に起動
  - **environment-based config**: dev/staging/prod を環境変数で切替
  - **Secrets management**: 環境変数より**Docker secrets**が本番推奨
  - **Health check endpoints**: orchestrator がプローブする `/health` エンドポイント
- **教訓**:
  1. **`condition: service_healthy`** は docker-compose の重要テクニック
  2. MemoryMCP のヘルスチェックは `/health` で実装すべき

#### MyMCPTools "Production Docker-Compose Setup"
- **URL**: https://mymcptools.com/blog/deploying-mcp-to-docker
- **キーパターン**:
  - **Multi-server orchestration**: 5+ サーバーを compose で
  - **Resource limits**: CPU/memory で暴走防止
  - **`read_only: true` + `tmpfs: /tmp`**: ルートFSを読み込み専用
  - **`cap_drop: [ALL]` + `security_opt: no-new-privileges`**: セキュリティ強化
  - **分離ネットワーク**: `internal: true` で外部通信遮断
  - **Docker secrets**: 環境変数より安全
- **教訓**:
  1. **`read_only + tmpfs + cap_drop` の3点セット**で hardening
  2. MemoryMCP の `Dockerfile.sandbox` は既に secure pattern を取り込み済み

#### DEV.to "Production Docker-Compose Setup" (kevinten10)
- **URL**: https://dev.to/kevinten10/mcp-server-docker-the-complete-production-docker-compose-setup-i-wish-i-had-when-i-started-after-4nhd
- **スタック**: Java + Spring Boot + MCP + PostgreSQL + Redis + nginx
- **キーパターン**:
  - **nginx reverse proxy** with TLS termination
  - **healthcheck + depends_on + restart: unless-stopped**
  - **nginx SSE buffering 無効化**: `proxy_buffering off` (重要！)
- **SSE buffering 問題**:
  - デフォルトでは nginx が SSE ストリームをバッファし、接続クローズ時に一括送信
  - **リアルタイム性が壊れる** ので `proxy_buffering off` 必須
- **教訓**:
  1. **MCP サーバーを nginx 後ろに置く場合、SSE buffering off 必須**
  2. MemoryMCP の EventBus + SSE は要注意（既存の本番デプロイに影響）

### MemoryMCPへの教訓（Docker）

1. **既存 Dockerfile の構造確認**:
   - 既に sandbox 機能あり（MEMORY.md 参照）
   - WSL2 + Docker バインドマウント対応（uid 合わせ）済み
2. **`Dockerfile.sandbox` の追加**（既存）は正しい方向
3. **depends_on with `condition: service_healthy`** を docker-compose.yml に導入
4. **Health check endpoint `/health`** の実装（FastMCP の `custom_route` で可能）
5. **nginx 経由の SSE buffering off** を本番 compose に追加
6. **DinD vs DooD の選択**: MemoryMCP の sandbox は DooD 寄り（socket マウント不要で済みそう）
7. **Docker MCP Toolkit** の **2GB/1CPU リミット** を参考に MemoryMCP のリソース設計
8. **Secrets** は環境変数より **Docker secrets** または `.env` + `chmod 600`
9. **Multi-stage build** でイメージサイズ削減（sandbox で既に対応？）
10. **Image signing + SBOM** はエンタープライズ要件次第で追加検討

---

## 横断的な教訓（MemoryMCP vNext に向けて）

### 実装パターン Top 5

1. **Capability Discovery Protocol** (画像生成): 起動時にプロバイダー能力を返却し、ルーターが capability サーフェスに問い合わせる
2. **Library Fallback Chain** (PDF): PyMuPDF → pdfplumber → pypdf のようにフォールバック連鎖
3. **4-tier Memory Lifecycle** (メモリ): Active → Superseded → Tombstoned → Hard-deleted
4. **KNN + FTS5 + RRF Hybrid Search** (メモリ): ベクトルと BM25 を並列実行 → RRF でマージ
5. **Progressive Disclosure** (スキル): name/description のみ起動時ロード、SKILL.md は必要な時だけ

### 設計上の Top 3 推奨

1. **Hexagonal Architecture**: Domain / Application / Infrastructure / McpHost / Tests の6レイヤー分離
2. **stdlib stderr separation**: stdout は JSON-RPC 専用、ログは stderr（Ozymandros パターンは必須）
3. **Fail-fast startup**: 設定・依存関係・モデル読み込みを接続受付前に完全検証

### LLM UX 改善 Top 3

1. **Tool description のカスタマイズ環境変数**（`TOOL_STORE_DESCRIPTION` パターン）
2. **`explain=true` でスコア分解** を返す（Ebbinghaus スコアの根拠を可視化）
3. **段階的 graceful degradation**（OCR 無しでも PDF 読める、embedding 失敗でも LIKE で動く）

### セキュリティ Top 3

1. **DooD 採用時の socket マウントリスク** を認識し、Trusted image のみ実行
2. **`read_only: true` + `tmpfs` + `cap_drop: [ALL]`** の hardening
3. **Secrets detection** + **Tool request interception**（機密情報のリクエストをブロック）

### MemoryMCP の現状評価

| 領域 | 現状 | 業界標準 | 評価 |
|---|---|---|---|
| 画像生成 | OpenAI互換（content配列） | base64 ImageContent | **◎ 標準準拠** |
| PDF | 無し | フォールバック連鎖 + OCR | **△ 機会あり** |
| スキル | plugins/ ディレクトリ着手 | SKILL.md 標準 | **○ 進行中** |
| メモリ | SQLite + Qdrant + Ebbinghaus | SQLite + 4-tier + hybrid RRF | **◎ 高レベル** |
| Docker | 既存 + sandbox | DooD + secrets + healthcheck | **◎ 良好** |

### 次のアクション候補

1. **PDF capability 追加**: PyMuPDF + pdfplumber + Tesseract-jpn のフォールバック実装
2. **Agent Skills 標準への正式移行**: 既存 plugins/ を `SKILL.md` 形式に統一
3. **4-tier lifecycle 導入**: MemoryMCP の Ebbinghaus に統合（active/superseded/tombstoned/hard-deleted）
4. **KNN + FTS5 + RRF ハイブリッド検索**: Qdrant 依存を保ちつつ SQLite FTS5 も活用
5. **Docker hardening 強化**: `read_only: true` + `cap_drop: [ALL]` を sandbox image に追加
6. **Health check endpoint `/health`**: FastMCP `custom_route` で実装
7. **`as_of` パラメータ追加**: 時系列クエリ対応
8. **Tool description カスタマイズ環境変数**: `MEMORY_MCP_TOOL_*_DESCRIPTION` パターン
