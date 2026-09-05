# アーキテクチャ

Nous の技術スタック、ディレクトリ構造、設計パターンを解説します。

---

## 技術スタック

| カテゴリ | 技術 |
|----------|------|
| 言語 | Python 3.12+ |
| MCP フレームワーク | MCPServer（`mcp` パッケージ v2 API） |
| HTTP フレームワーク | Starlette（`mcp` に同梱、SecurityHeaders + CORS ミドルウェア付き） |
| データベース | SQLite（WAL モード） |
| ベクトルストア | Qdrant |
| 埋め込みモデル | cl-nagoya/ruri-v3-30m（日本語特化） |
| Reranker | hotchpotch/japanese-reranker-xsmall-v2 |
| 形態素解析 | SudachiPy |
| 設定管理 | Pydantic v2 |
| ロギング | structlog |
| コンテナ | Docker / Docker Compose |
| フロントエンド | Vanilla JS (IIFE + loader、`window.Nous` 名前空間) + CSS (@layer) |
| テスト | pytest + Vitest |

---

## ディレクトリ構造

```
nous/
├── main.py                    # エントリーポイント（FastMCP app生成）
├── api/
│   ├── mcp/                   # MCPツール実装
│   │   ├── tools.py           # TOOL_DISPATCH + register_tools()
│   │   ├── _tools_memory.py   # memory CRUD/Search/Stats
│   │   ├── _tools_item.py     # item Add/Equip/Search
│   │   ├── _tools_goal.py     # goal Manage
│   │   ├── _tools_persona.py  # get/update context
│   │   └── _tools_skill.py    # invoke_skill
│   └── http/
│       ├── routers/           # REST APIエンドポイント
│       │   ├── chat/          # SSEストリーム/メッセージ/セッション
│       │   ├── persona/       # ペルソナCRUD/ヘルス/ダッシュボード
│       │   ├── tts.py         # 音声合成
│       │   ├── image_gen.py   # 画像生成
│       │   └── ...
│       ├── sections/          # HTMLテンプレート（Pythonレンダリング）
│       │   ├── chat/          # チャットUI 7モジュール
│       │   ├── memories.py    # 記憶タブ
│       │   ├── timeline.py    # タイムライン
│       │   └── ...
│       └── static/            # 静的ファイル
│           ├── core/          # 18ファイル（API/DOM/SSE/Store/Toast等）
│           ├── chat/          # 14ファイル（チャット機能）
│           ├── features/      # 17ファイル（タブ機能）
│           ├── components/    # 3ファイル（共通UI部品）
│           └── styles/        # 7ファイル（CSSレイヤー）
├── application/               # ビジネスロジック
│   ├── chat/                  # チャットパイプライン
│   │   ├── pipeline/          # 準備→推論→圧縮→投稿
│   │   ├── tools/             # 組み込みツール定義
│   │   └── service.py         # チャットサービス
│   ├── workers/               # バックグラウンドワーカー
│   │   ├── decay_worker.py    # 感情/体調減衰＋リンク減衰
│   │   └── consolidation_worker.py  # 記憶統合
│   └── use_cases.py           # AppContextRegistry
├── domain/                    # ドメインモデル
│   ├── memory/                # 記憶エンティティ/サービス/リポジトリ
│   │   ├── entities.py        # Memory, Entity, Relation
│   │   ├── service.py         # MemoryService (Facade)
│   │   ├── write_service.py   # 書込専用
│   │   ├── query_service.py   # 照会専用
│   │   ├── link_service.py    # ヒュッビアンの結合
│   │   └── evolution_service.py # 記憶進化
│   ├── persona/               # ペルソナエンティティ
│   │   ├── entities.py        # Persona, BodyState
│   │   ├── body_decay.py      # 身体数値減衰
│   │   └── emotion_decay.py   # 感情減衰（Ebbinghaus）
│   ├── search/                # 検索エンジン
│   │   ├── engine.py          # ハイブリッド検索
│   │   ├── ranker.py          # RRFスコアリング
│   │   └── spreading_activation.py # 活性化拡散
│   ├── equipment/             # アイテム/装備システム
│   └── chat_config.py         # ChatConfig Facade（サブ設定統合）
├── infrastructure/            # 基盤層
│   ├── llm/                   # LLMプロバイダ実装
│   │   ├── openai_compat.py   # unified provider (all connections; OpenAI/OpenRouter/Anthropic-compat)
│   │   └── cache_utils.py     # プロンプトキャッシュ共通化
│   ├── embedding/             # 埋め込みモデル
│   ├── qdrant/                # Qdrantクライアントアダプタ
│   ├── sqlite/                # SQLiteリポジトリ群
│   │   ├── base_repo.py       # SQLiteRepository基底
│   │   ├── memory_crud_repo.py
│   │   ├── memory_search_repo.py
│   │   └── ...
│   ├── image_gen/             # 画像生成アダプタ
│   ├── voice/                 # TTSアダプタ
│   └── mcp_client/            # MCPクライアント（他サーバー連携用）
├── config/                    # 設定
│   ├── settings.py            # Settings (Pydantic)
│   └── runtime_config.py      # ランタイム設定
├── migration/                 # データマイグレーション
│   ├── importers/             # JSONL/Convo/Legacy importer
│   └── exporters/             # JSONL exporter
└── cli/                       # コマンドラインインターフェース
```

---

## データフロー（チャット処理）

```
ユーザーメッセージ
    ↓
[HTTP Router] chat_stream.py (SSE)
    ↓
[Pipeline] prepare.py → context_loader.py → memory_retriever.py
    ↓ (ハイブリッド検索: ベクトル+キーワード+RRF)
[Pipeline] prompt.py → system prompt構築（キャッシュ対応）
    ↓
[Inference] LLM API (OpenAI-compatible; Anthropic/Gemini via compat endpoints)
    ↓ (ツール呼出: memory_search, update_context, invoke_skill...)
[Tool Execution] builtin.py → MCPツール実行
    ↓
[Response] stream text_delta → SSE client
    ↓
[Post-processing] summarizer.py → compress.py → trimmer.py
    ↓
[Memory Write] memory_create → vectorize → Qdrant index
    ↓
[Background] decay_worker / consolidation_worker / snapshot_worker
```

---

## 設計パターン

| パターン | 適用箇所 |
|----------|----------|
| **Facade** | MemoryService（Write/Enrich/Link/Evolution/Query）、ChatConfig |
| **Mixin 多重継承** | SQLiteリポジトリ（CRUD/Search/Stats/Version） |
| **Result Monad** | `Result[T, E]` with `and_then`/`or_else` |
| **Mutable Wrapper** | `_search_engine = [None]` で後注入 |
| **Pub/Sub Store** | JS store（双方向同期 via `Object.defineProperty`） |
| **名前空間統一** | `N.Core.*`, `N.Chat.*`, `N.Features.*` |

---

## MCP ツール一覧

| カテゴリ | ツール名 | 説明 |
|----------|----------|------|
| **記憶** | `memory_create` | 永続記憶を作成（importance/tags/kind/emotion付き） |
| | `memory_read` | キー指定または最新リスト取得 |
| | `memory_update` | 既存記憶を上書き更新 |
| | `memory_delete` | 論理削除（tombstone） |
| | `memory_search` | ハイブリッド検索（ベクトル+キーワード+RRFスコアリング） |
| | `memory_stats` | 統計（総数/タグ分布/感情分布） |
| **コンテキスト** | `get_context` | ペルソナ状態＋記憶概要（セッション開始時に第一呼出推奨） |
| | `update_context` | 感情・体調・環境・関係性を更新 |
| **アイテム** | `item_add` | インベントリに物理アイテムを追加 |
| | `item_equip` | 装備スロットにセット |
| | `item_search` | インベントリ検索 |
| **目標** | `goal_manage` | 目標の作成/一覧/達成/取消 |
| **スキル** | `invoke_skill` | 内蔵スキルの自律呼び出し |
| | `list_skills` | 登録済みスキル一覧 |
| **発見** | `search_tools` | ベクトルベースのツール検索 |
| **画像生成** | `image_generate` | ComfyUI連携 AI画像生成（Danbooruタグ形式） |

---

## 内蔵スキル

| スキル | 説明 |
|--------|------|
| `auto-memory` | 会話中の重要情報を自動記録 |
| `goal-coach` | 目標管理のコーチング |
| `image-gen` | 画像生成の指示最適化 |
| `mood-sync` | 感情変化の自律検出・反映 |
| `recall-weaver` | 関連記憶の想起・連鎖 |

---

## 環境変数

| 環境変数 | デフォルト | 説明 |
|----------|-----------|------|
| `NOUS_DATA_ROOT` | `./data` | 全データの保存先 |
| `NOUS_SERVER__PORT` | `26262` | HTTP ポート |
| `NOUS_SERVER__HOST` | `0.0.0.0` | バインドアドレス。公開する場合は `NOUS_API_KEY` を事前設定すること（未設定はdev素通し）。 |
| `NOUS_API_KEY` | `""`（空） | HTTP Bearer 資格情報。空はdev素通し（Bearer=persona名）。非空時は Bearer 一致必須（401）。復旧は `{data_root}/config/config_overrides.json` の `general.api_key` 削除→再起動。 |
| `NOUS_CORS_ALLOWED_ORIGINS` | （未設定） | CORS上書き（カンマ区切り or JSON配列）。既定はlocalhost開発originのみ。`" * "` は明示時のみ（credentials強制off）。 |
| `NOUS_QDRANT__URL` | `http://localhost:6333` | Qdrant 接続先 |
| `NOUS_EMBEDDING__MODEL` | `cl-nagoya/ruri-v3-30m` | 埋め込みモデル（日本語特化） |
| `NOUS_DEFAULT_PERSONA` | `default` | デフォルト Persona 名 |
| `NOUS_TIMEZONE` | `Asia/Tokyo` | タイムゾーン |
| `NOUS_SANDBOX__ENABLED` | `true` | コード実行サンドボックス |
| `NOUS_MEMORY_ENRICHMENT__ENABLED` | `true` | 記憶作成時の LLM 自動補完 |
| `NOUS_FORGETTING__ENABLED` | `true` | Ebbinghaus 忘却曲線 |

全設定項目は WebUI の**設定画面**から確認・変更できます（WebUI からの変更は `docker-compose.yml` の環境変数より優先されます）。
