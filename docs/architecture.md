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

```text
nous/
├── main.py                    # エントリーポイント（FastMCP app生成）
├── api/
│   ├── mcp/                   # MCPツール実装
│   │   ├── tools.py           # TOOL_DISPATCH + register_tools()
│   │   ├── _tools_memory.py   # memory CRUD/Search/Stats
│   │   ├── _tools_item.py     # item Add/Equip/Search
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
│           └── styles/        # 9ファイル（CSSレイヤー: variables/reset/theme/layout/components/sections/chat/chat-mobile/utilities）
├── application/               # ビジネスロジック
│   ├── chat/                  # チャットパイプライン
│   │   ├── pipeline/          # 準備→推論→圧縮→投稿
│   │   ├── tools/             # 組み込みツール定義
│   │   └── service.py         # チャットサービス
│   ├── workers/               # バックグラウンドワーカー
│   │   ├── wiki_worker.py           # 記憶編纂
│   │   └── prospective_worker.py    # agent:task 予約ターンの 1h 巡回
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

送信 → 受付 → 配信 → パイプライン → 後処理の全段は
[chat-flow.md](chat-flow.md) にまとめてある（図・イベント一覧・異常系・設定ノブ）。

要点だけ:

```text
POST /api/chat/{persona}            202 {turn_id} / 409（同時1ターン）
    ↓ サーバー内タスクで完遂（クライアント切断に影響されない）
PrepareStep → PromptBuildStep → CompressStep → InferenceStep
    ↓ 本文 delta は EventBus を通さず TurnHub のリングバッファへ
GET /api/chat/{persona}/events?last_seq=N   replay + live + keepalive 15s
    ↓
DoneSSE →（end_turn: ターン枠を解放）
    ↓ ターン枠の外（_spawn_turn）
PostProcessStep（記憶抽出・状態更新）
```

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
| **コンテキスト** | `session_begin` | ペルソナ状態＋記憶概要（セッション開始時に第一呼出推奨） |
| | `get_context` | `session_begin` の互換別名（旧名） |
| | `update_context` | 感情・体調・環境・関係性を更新 |
| **アイテム** | `item_add` | インベントリに物理アイテムを追加 |
| | `item_equip` | 装備スロットにセット |
| | `item_unequip` | 装備スロットを外す（外見は自動再構築） |
| | `item_search` | インベントリ検索 |
| **Wiki** | `wiki_read` | slug 指定でページ本文＋メタを読む |
| | `wiki_ls` | ページ一覧（project / tag / category 絞り込み） |
| | `wiki_grep` | 本文を行単位の正規表現で grep |
| | `wiki_write` | ページを書く（slug 規約 `project-<slug>-<topic>` / `<persona>-<topic>`、`sources` に根拠記憶 key） |
| | `wiki_delete` | ページ削除（`index` は拒否、検索索引からも削除） |

MCP として公開しないチャット組み込みツール（`move` / `invoke_skill` / `list_skills` / `search_tools` / `image_generate`）は `nous/application/chat/tools/` にあり、チャット経路でのみ使う。

ワークスペースツール（`bash` / `read_file` / `write_file` / `edit_file`）は `nous/application/chat/tools/shell.py` にある。`ToolConfig.workspace_root` が未設定なら公開されない（オプトイン）。ただし sandbox が有効（`ToolConfig.sandbox_enabled` + `sandbox_manager_url`、または compose の `NOUS_SANDBOX_*`）なら、この 4 本は `sandbox_shell.run_tool` 経由でコンテナ内実行になり、`workspace_root` は不要（別ツール `sandbox` は出さない — モデルに見せるシェルは 1 本だけ）。境界は `workspace_root` の `resolve()` 前方一致で、symlink も潰れる。`bash` は末尾 120 行だけを返し、全文は `{data_root}/persona/{persona}/artifacts/{session_id}/` に落ちる。実行内容（`command` / `exit_code`）は `tool.called` イベントの payload に載る。

エージェント→ユーザーのファイル受け渡しは `attach_file`（`nous/application/chat/tools/attachments.py`）。ワークスペースのファイルを `persona/{persona}/uploads` に複製し、`file_attach` SSE でチップを出す。配信はユーザー添付と同じ `GET /api/chat/{persona}/attachment/{filename}` で、扱いはワークスペースツールと同じくオプトイン（sandbox 稼働中でも可）。sandbox 稼働時はコンテナ内で `cp` する（uploads は `/home/agent/uploads` にマウント済み）。上限 10MB。

---

## 内蔵スキル

| スキル | 説明 |
|--------|------|
| `auto-memory` | 会話中の重要情報を自動記録 |
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
| `NOUS_PLUGIN__API_KEY` | `""`（空） | pi 拡張の ingest（`/api/events/ingest`）·wiki 手動起動の鍵。空なら 503。検索（`/api/search`）は `NOUS_API_KEY`（general）で守られるので、両方設定する環境では pi 拡張側に `NOUS_API_KEY` か `nous.json` の `searchApiKey` を渡すこと（未設定なら plugin key で検索するため 401 になる）。 |
| `NOUS_QDRANT__URL` | `http://localhost:6333` | Qdrant 接続先 |
| `NOUS_EMBEDDING__MODEL` | `cl-nagoya/ruri-v3-30m` | 埋め込みモデル（日本語特化） |
| `NOUS_DEFAULT_PERSONA` | `default` | デフォルト Persona 名 |
| `NOUS_TIMEZONE` | `Asia/Tokyo` | タイムゾーン |
| `NOUS_MEMORY_ENRICHMENT__ENABLED` | `true` | 脳側 LLM（矛盾判定）の有効化。enrichment 自体は 2026-11-08 廃止、自発的内省・独り言は 2026-11-09 廃止 |

全設定項目は WebUI の**設定画面**から確認・変更できます（WebUI からの変更は `docker-compose.yml` の環境変数より優先されます）。

## 検索品質（ASIST 反映、2026-10-04）

### 検索パイプラインの現状

- ハイブリッド検索 = semantic（Qdrant）+ keyword（SQLite FTS5）+ OR-fallback、RRF スコアリング。
- **dominantTokenKind 別 bm25 バー**（item 5）: OR-fallback 候補にのみ bm25 バーを適用。
  - 閾値 `INJECTION_MAX_BM25 = { bigram: -2.5, word: -5.0 }`（正規化スコア `bar/(1+bar)` で比較）
  - classify: `nous/domain/search/token_kind_gate.py`（cjk/lat トークン数で bigram/word/mixed 判定、mixed は gate 無効・fail-open）
  - 設定: `Settings.search.injection_max_bm25` / env `NOUS_SEARCH__INJECTION_MAX_BM25`
  - all-term exact マッチは boost 1.0 でバーを必ず通過
- **注入済み記憶排除**（item 1）: チャット経路で同一 turn 内に注入済みの記憶を検索結果から除外。
- **再 encode 排除（fingerprint）**（item 6）: Qdrant アダプタが embedding fingerprint を payload に記録し、同一 fingerprint の upsert は再 encode をスキップ。
- **日次 wiki 編纂（item 5）**: `WikiWorker` が定刻（既定 03:00 JST = `NOUS_WIKI__RUN_AT_TZ`、`--hour` は `NOUS_WIKI__RUN_AT_HOUR`）に起動し、未編纂の記憶をトピックページへまとめ、源記憶を `archived` に落とす。LLM が空応答/切れ JSON を返した場合は max_tokens を 2 倍にして 1 回だけ再試行し、サイクル内に error が残ったら 30 分後に再挑戦する（丸 1 日空けない）。定刻に persona コンテキストがまだ 1 つも無い場合（初リクエスト前・再起動直後）も空振りとして扱い、同じ 30 分後に再挑戦する（以前は for が 0 回で静かに終わり丸 1 日を捨てていた）。編纂が使う LLM は既定で**そのペルソナのチャット設定（チャットタブのプロバイダ/モデル/鍵/base_url）を流用**し（`nous/application/wiki/llm_target.py`）、`NOUS_WIKI__API_KEY` 等を明示した場合だけ wiki 専用設定が優先される。
  1 サイクルは 3 段: (1) 前日（JST）の記憶・`session_events` の営み・人物設定から起こした暮らし（`life_enabled`、記憶には残さない）から `journal-YYYY-MM-DD` 日記ページを作る、(2) トピックページを編纂する、(3) 編纂応答の `conflicts` / `questions` を監査イベントと `open-question` 記憶に落とす（追加 LLM 呼び出しなし）。続いて `questions` を**persona に登録済みの MCP ツールだけ**で調べ（`research_enabled`、既定 `false`）、URL が取れたものだけページ末尾の `## 外部情報` に追記する。ツール 0 件なら何もしない（`skipped: no mcp tool` の 1 行）。日記を書いた直後には `journal_tomorrow_tasks`（既定 true）で日記から「明日やること」を最大 `journal_tomorrow_max`（既定 3）件起こし、`agent:task` + `cue:time:` の予定として登録する（追加 LLM 呼び出し 1 回、実行は `ProspectiveWorker` の毎時照合）。抽出に失敗しても日記は書き終えているので `warning:` 止まりでサイクルは失敗させない。
  記憶層の矛盾掃除は週 1 回（`memory_conflict_interval_hours`=168）別建てで走る: 同 project タグ + 本文 Jaccard + 数値の食い違いで候補を純関数抽出し（LLM 0 回）、`classify_contradiction` を `memory_conflict_max_pairs`=10 件まで適用、矛盾なら古い側の `valid_until` を閉じて `superseded_by` で繋ぐ（削除しない）。全件判定不能な回は `warning:` で記録し、週次ゲートを再武装しない。

- **記憶の干渉とマージレビュー（audit M1）**: 記憶書込時の既存エボリューション検索結果を再利用し、類似度 `0.85–0.95` の既存側に `interference_count` を加算する（検索回数は増えない）。同じペアで 3 回に達したら `session_events` に `memory.merge_review`（`session_id=memory_write`、summary `merge review: {key} ~ {other_key}`）を 1 件置く。人手（またはエージェント）がマージを検討するキューで、自動マージはしない。
- **感情の効き方（audit H4/H5）**: 感情強度は検索時の salience（`RankPolicy.emotion_salience_weight`=0.1）にのみ寄与し、永続 `stability` を膨らませない（`emotion_peak` 列は書込・参照とも廃止、DROP は v5）。過去に膨らんだ行はマイグレーション v13 が 1 回だけ 1.0 に clamp する（LTM は対象外）。

残る常駐 worker は `WikiWorker` のみ（ConsolidationWorker は 2026-11 に撤去。Curation / Freshness / Enrichment / Decay は 2026-11-08 に廃止）。

### 評価ハーネス

- `scripts/eval_search_quality.py`（gold コーパス: `tests/benchmark/data/verify_corpus_v1.json`）
- `scripts/eval_real_queries.py`（実クエリ A/B）
- `scripts/search_quality_smoke.py`（CI 用スモーク: 固定小コーパス `tests/benchmark/data/search_quality_smoke.json`、オフライン keyword 経路、`recall@5 ≥ 0.8` / `MRR ≥ 0.7` / zero-result 0。`make search-quality-smoke`、artifact は `output/search_quality_smoke.{json,md}`）
- 合格ライン（案C）: zero-result 0 / recall@5 ≥ 0.75 / MRR ≥ 0.80 / p95 ≤ 1.5s

### ドリフト検知

- `scripts/check_docs_drift.py`（`make docs-drift`）: `@_tool("...")` ↔ `docs/architecture.md` の MCP ツール表、`custom_route(...)` ↔ `docs/http_api_reference.md` のエンドポイント、`Settings` ↔ ドキュメントの `NOUS_*` を突き合わせる。ドキュメントにあるが実装に無いものは error、実装にあるが未記載の HTTP は `scripts/docs_drift_baseline.json` に既知分を記録し新規だけ error。加えて `requirements-prod.txt` が `pyproject.toml` の `[project.dependencies]` の転記と完全一致するか（双方向、行末コメントは除外）も検査する。
