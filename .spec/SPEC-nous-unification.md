# SPEC — 記憶の nous 一元化（セッションまたぎ再開の自然化）

> 出典: ユーザー要望 (2026-08-14)。調査: exp-1（nous 記憶実装）/ exp-2（make_project_skill 詳細）/ exp-3（フック設計・スキル配置）/ lib-1・lib-2（外部運用事例 30件超）
> 状態: **設計書 v5**（PoC 検証結果を反映: evolution タグ破壊バグの修正を main 反映済み・サーバー側タグ強制を R3 に追加）。実装は合意後のフェーズ分け（実装方針参照）で開始。

## 背景

セッションまたぎで「自然な会話再開」ができない。調査で判明した現状:

- **記憶が3層に分離し、互いに読んでいない**:
  - nous サーバー（MCP）: 会話・感情・ペルソナ記憶。毎ターン MemoryLLM が facts/goals を自動抽出（`nous/application/chat/memory_extractor.py:187`）
  - スキル群（`~/.agents/skills/`）: session-start / auto-memory / recall-weaver / mood-sync / goal-coach が MCP ツールをプロンプト経由で手動呼出
  - `.agent/` ファイル: MEMORY.md（開発教訓）・HANDOFF.md（作業引継）。make_project_skill が生成、手動運用
  - **橋渡しコードは存在しない**（.agent/ を読む .py は grep 0 件）。開発教訓キーワードは nous 記憶に 0 ヒット
- **セッション終了フックが無い**: プラグイン `plugins/opencode-memory-sync/src/index.ts:247` の dispose() が session.stopped を送信するが、nous 側に `session.end` ハンドラが存在しない。会話サマリは「メッセージ追い出し（evict）」時のみ生成（`application/chat/summarizer.py:30`、`session_window.py:110-115`）→ **短いセッションではサマリが永遠に生成されない**
- **.agent/ 運用の実質死亡**: HANDOFF.md は 2026-08-08 で停止（終了トリガー不在）。MEMORY.md は 08-14 まで生きている（作業完了トリガーはある）→ トリガーの強さで更新率が決まる
- **読み取りの質**: get_context に重複除去なし（top_memories と recent が独立取得、`_tools_persona.py:46,71`）。関係性減衰 `_apply_relationship_decay` はデッドコード（`_tools_helpers.py:307`）。「前回何を話したか」の直近サマリが薄い
- **二重記録**: スキル経由の手動 memory_create × サーバー自動抽出（類似度>0.85 ガードのみ）× .agent/ 手動更新の3経路
- **スキル群の構成問題**: make_project_skill が旧世界（.agent/ 生成・/handoff コマンド二重保存）を量産し続け、nous 一元化と矛盾

**方針（ユーザー合意済み）**: 書き込み・読み取りを nous に完全一元化。.agent/ は**完全廃止**（git 追跡済み 72 ファイルは履歴に残る）。スキル群は nous 付属（プロジェクト内 git 管理）に移管し、**make-project / session-start / project-manage に再編成**（make_project_skill のみ改名、統合はしない）。

## 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | セッション終了フック | nous サーバーに `session.stopped` イベントハンドラを追加。終了時に未サマリ化メッセージからサマリを生成し `memory_create(tags=["session_summary"])`。詳細設計は「フック設計」節 |
| R2 | サマリ生成の即時化 | セッションが短く evict 未発生でも、終了時に必ずサマリが生成される |
| R3 | 開発知識の nous 化 | 開発教訓を専用 persona（`dev`）の記憶として記録。**プロジェクトタグ必須**（「記憶・検索設計」節）。会話ペルソナ（herta 等）への混入を防ぐ |
| R4 | 作業引継の nous 化 | HANDOFF.md 相当は session_summary（+ source_context にブランチ・コミット情報）で代替。開始時は直近 session_summary を読む（**memory_search に `sort="updated_at"` オプションを追加し、`tags=["session_summary"], top_k=1` で最新1件を取得。案2採用**） |
| R5 | get_context 改善 | (a) top_memories と recent の重複除去 (b) 直近 session_summary を優先表示 (c) `_apply_relationship_decay` のデッドコード整理 |
| R6 | スキル再編成 | 下記「スキル再編成」表の通り。goal-coach → project-manage に全統合、make_project_skill → **make-project** に改名 |
| R7 | .agent/ 運用廃止 | AGENTS.md の「MEMORY.md / HANDOFF.md 読込」ルールを削除し session-start の get_context に一本化。make-project が .agent/ を**生成しない**。既存ファイルはアーカイブ放置 |
| R8 | スキル配置一本化 | 正配置 `Nous/.claude/skills/<name>/SKILL.md`。`data/skills` は symlink 化。opencode / Claude Code / nous invoke_skill の3経路対応 |
| R9 | 名前変更の波及更新 | make_project_skill → make-project の参照更新: oh-my-opencode-slim.json（2 preset）、`~/.agents/AGENTS.md:93`、session-start 内言及、data/skills ディレクトリ名 |

### スキル再編成（R6 詳細）

| 旧スキル | 新スキル | スコープ | 発動条件・頻度 |
|----------|----------|----------|----------------|
| make_project_skill | **make-project**（改名のみ） | プロジェクト初期構築。**.agent/ 生成を廃止**。初期記憶を `memory_create`（dev persona・`project_overview`）で記録。**AGENTS.md にプロジェクトタグ節を生成**。残す本質: `.spec/` 4ファイル + SDD、品質ゲート節、README/CLAUDE/GEMINI、git init | 「プロジェクトを初期化/セットアップして」。低頻度（手動） |
| session-start | **session-start**（名称維持） | セッション開始ルーティン。get_context + **AGENTS.md のプロジェクトタグ読取 → プロジェクト絞り込み検索** | セッション開始時・最初の応答前。毎セッション1回 |
| goal-coach | **project-manage** | **全統合**: (a) 目標管理: goal_manage (b) .spec/ 進行管理: PLAN/SPEC/TODO/KNOWLEDGE の進捗追跡・更新。SDD ルールは残し運用を補助 | 目標・進捗・TODO 関連の発言。中頻度 |

### 記憶・検索設計（R3/R4 詳細）— プロジェクトタグ方式

**目的**: dev persona は複数プロジェクトの記憶を扱うため、「そのプロジェクトの記憶」を確実に抽出できる必要がある。

**タグ体系**:
| タグ | kind | 内容 | 作成タイミング |
|------|------|------|----------------|
| `project:<slug>` | — | **全 dev 記憶に必須のプロジェクト識別タグ**。slug はディレクトリ名由来（例: `project:nous`） | 全記録時 |
| `project_overview` | semantic | プロジェクト概要・技術構成・主要決定 | make-project 初期構築時 |
| `dev_lesson` | procedural | 開発教訓・トラブル解決法 | トラブル解決後 |
| `decision` | semantic | 決定事項と理由 | アーキ判断時 |
| `task_state` | prospective | 進行中タスク・次の一手 | 作業中断時（project-manage） |
| `session_summary` | episodic | 会話の要約 | セッション終了フック（R1） |

**AGENTS.md への埋め込み**: make-project が AGENTS.md に以下の節を生成:
```
## プロジェクト識別
- project: <slug>
```
session-start は開始時にこの節を読み取り、以降の `memory_search` は必ず `tags=["project:<slug>", ...]` で絞り込む。会話ペルソナ（herta）の記憶と開発記憶（dev）は persona 分離 + プロジェクトタグの2重で交ざらない。

**検索フロー**:
1. セッション開始: session-start → get_context（状態+直近サマリ）+ AGENTS.md の project slug 読取
2. 開発中: `memory_search(tags=["project:<slug>", "dev_lesson"])` 等、タグ絞り込みのみ（全件検索禁止）
3. 引継: 直近 session_summary を優先表示（R5 の改善と連動）

### 発動頻度の数値設計（lib-1/lib-2 の実例反映）

外部実例（AgentOS: importance 0.4・maxPerTurn 3、PraisonAI: 0.7-0.8、AutoMem: 150-300字 target/500字 soft、cogmem: arousal>=0.5、Dooders: importance>=0.7）を踏まえた nous の基準:

| スキル | しきい値 | 上限 | 備考 |
|--------|----------|------|------|
| auto-memory | **importance >= 0.6**（現状 0.3〜 を引き上げ） | 1ターン3件（既存維持） | ルーチン記録はサーバー自動抽出に委ね、スキルは高重要度のみ |
| mood-sync | emotion_intensity >= 0.5（既存維持） | 1ターン3件（既存維持） | 業界標準（cogmem arousal>=0.5）と一致確認済み。0.1 変動は無視（既存） |
| 記録粒度 | 内容 150-500字 | — | 150字未満=一文、500字超=要約して記録 |

### フック設計（R1/R2 詳細）— 調査確定版

**イベント経路（現状確認済み）**:
- opencode プラグイン dispose()（`plugins/opencode-memory-sync/src/index.ts:246-255`）が `type: "session.stopped"` + session_id + persona を `POST /api/events/ingest` へ送信
- nous 側は未知 type でも session_events テーブルに**記録するだけ**（`events.py:204-247`）で EventBus に流れない（SessionEventRecorder の購読6種のみ）→ **現状「記録されるが誰も消費しない」**

**実装（最小 diff・新規エンドポイント不要・プラグイン改修不要）**:
1. 既存の `EVENT_EVENTS_INGESTED` publish（`events.py:250-259`）をフックにし、受信イベント群に `type == "session.stopped"` を含むか検査
2. 含む場合: `SessionManager.get_or_create(persona, session_id)` でウィンドウ取得（session_id はプラグインが常に付与）
3. ウィンドウ内 `_messages`（= evict されていない未サマリ分）を **SessionSummarizer を再利用**して要約 → `memory_create(tags=["session_summary"])`（`summarizer.py:118-123` 踏襲）
4. 失敗は非致命（既存 evict の `contextlib.suppress(Exception)` 方式踏襲）。fire-and-forget の asyncio.create_task で実行

**二重生成ガード**:
- evict サマリ = 追い出した分、終了サマリ = 残り分 → 素直に分離される
- 残存リスク: サーバー途中再起動 + from_db 復元（`session_window.py:169-196`）で全メッセージ復元 → evict 済み分が再サマリされうる（「サマリ済み境界」が存在しない）
- **Phase A は最小実装**（空リストスキップ + 既存の類似度>0.85 重複スキップ）。重複が観測されたら「サマリ済み境界」（chat_sessions へのカラム追加 or ウィンドウ状態）を追加（ponytail: 要検討事項として明記）

### 制約
- **破壊的変更なし**: 既存 memory_create / get_context / スキーマは変更しない。追加はイベントハンドラ + 表示ロジック + スキルファイル群のみ
- MCP ツールの追加・変更がある場合は `docs/llm_usage_guide.md` 更新必須
- `dev` persona は新規作成だが、persona ごとの memory.sqlite 分離が既存設計のため追加実装不要
- スキル配置: `data/skills/` は `.gitignore` の `data/*/`（.gitignore:45）と矛盾。新規スキルは `git add -f` 必要。symlink 化後は実体 `.claude/skills/` を追跡（.gitignore 調整）
- 旧グローバルスキル（make_project_skill / session-start / goal-coach）は**削除**し nous 付属版のみに（opencode の「一意」ルール違反回避）。auto-memory / recall-weaver / mood-sync は**グローバルのまま**（会話ペルソナ向け・他プロジェクトでも使用）。data/skills/ の既存6スキル（auto-memory, goal-coach, image-gen, item-manage, mood-sync, recall-weaver）は invoke_skill 用に配置済み — 配置変更は再編成対象（make-project / session-start / project-manage）のみ
- 既存テスト失敗 27 件は本件と無関係（2026-08-14 確認、worktree 比較で切り分け）

## 検証要件

| # | 項目 | 方法 |
|---|------|------|
| V1 | 終了フック | 短いセッション終了 → session_summary タグの記憶が生成される。evict 未発生でも生成されることをテストで確認 |
| V2 | サマリ内容 | 「何を話したか」「合意・約束」を含む（LLM 形式テスト）。文字化けチェック（既存 N'Ko/Mongolian/PUA チェック踏襲） |
| V3 | get_context | 同一記憶が2回表示されない。直近 session_summary が優先表示される |
| V4 | プロジェクト分離 | dev persona の記憶に `project:<slug>` が付与される（スキル経由 + サーバー側タグ強制の両経路で確認）。`memory_search(tags=["project:nous"])` で Nous の記憶だけが返る。herta の記憶に開発教訓が混入しない |
| V5 | スキル解決 | 3スキル（make-project / session-start / project-manage）が opencode・Claude Code・nous invoke_skill の3経路で解決される |
| V6 | .agent/ 非生成 | make-project で新プロジェクト構築 → `.agent/` と `.claude/commands/handoff.md` が生成されない。AGENTS.md に MEMORY.md/HANDOFF.md 読込ルールが含まれない |
| V7 | 回帰 | 変更モジュールに依存するテストのみ個別実行（フルスイート禁止）。既存失敗は worktree 比較で切り分け |
| V8 | lint/型 | ruff / py_compile PASS。UI 変更なし |
| V9 | 引継復元 | `memory_search(tags=["session_summary"], top_k=1, sort="updated_at")` が最新1件のみ返る（古いサマリが混ざらない） |

## 実装方針（合意後のフェーズ分け案）

各フェーズは独立領域 → 並列 #011 実行可能。実装開始前にユーザー承認を得る。

- **Phase A: R1+R2（終了フック）+ R4 読み取り手段** — nous サーバー側イベント処理 + **memory_search の `sort="updated_at"` オプション追加** + テスト。単一領域。SessionSummarizer を再利用
- **Phase B: R3+R4+R7（一元化 + .agent/ 廃止）** — dev persona 運用 + プロジェクトタグ設計 + AGENTS.md ルール変更 + make-project の .agent/ 非生成化。ユーザー確認必須（作業フロー変更）
- **Phase C: R5（get_context 改善）** — 独立。重複除去 + サマリ優先表示 + デッドコード整理
- **Phase D: R6+R8+R9（スキル再編成）** — project-manage 作成（goal-coach から拡張）、make-project 改名・nous 付属化（SKILL.md 書き換え）、session-start の nous 付属化（プロジェクトタグ読取 + **最新 session_summary 復元: `memory_search(tags=["session_summary"], top_k=1, sort="updated_at")`**）、配置変更（.claude/skills/ + data/skills symlink）、旧スキル削除、登録更新（oh-my-opencode-slim.json 等）、**config.json の enabled_skills への新スキル登録（PoC 発見3: data/skills/ 配置のみでは LLM が存在を認識できない）**
- ドキュメント: MCP ツール変更時 `docs/llm_usage_guide.md`。本 SPEC に実装結果を追記

---

## PoC 検証結果（2026-08-14、ブランチ poc/skill-poc）

検証目的: 再編成スキル群を実際の LLM に使わせ、記憶管理が機能するか本実装前に確認する。

### 検証環境
- dev persona（新規作成）、Docker コンテナ（localhost:26262）、OpenRouter 経由
- モデル2系統で比較: `openrouter/free` → `deepseek/deepseek-v4-flash`（本番想定相当）
- 試作スキル3つ（make-project / project-manage / session-start）を `data/skills/` に配置

### 発見1: evolution タグ破壊バグ（重大・修正済み）
- memory_create の tags（`project:<slug>` 等）が、数分後のバックグラウンド evolution で無検証に全置換されるバグを発見（tags → `["last_reflection"]`）
- 原因: `MemoryEvolutionService._evolve_related_memories` の EXTENDABLE 分岐（evolution_service.py:97-100）が LLM 生成 `updated_fields.tags` を既存記憶へ無検証適用。reflection 自動作成が evolution を連鎖起動
- 修正（**main e7354bd1 / poc c9245284、両ブランチ反映済み**）:
  1. プロンプトで「tags 変更禁止・importance のみ」を明示（contradiction.py CLASSIFY_PROMPT）
  2. パーサーで updated_fields をホワイトリスト化（importance 数値のみ許可、contradiction.py `_parse_contradiction_response`）
  3. サービス側で tags/content を強制除去（二重ガード、evolution_service.py）
  4. evolution 更新に version 記録追加（`save_version(changed_by="evolution")`、監査可能化）
- 実環境検証: 修正後、evolution が3回ヒット（access=3）しても tags 無傷。回帰テスト4件追加（test_contradiction.py 13 passed）

### 発見2: スキル駆動はモデル能力に依存
| 項目 | openrouter/free | deepseek-v4-flash |
|------|----------------|-------------------|
| スキル invoke | しない（直接ツール実行） | する（goal-coach / auto-memory をロード） |
| ツール連鎖 | 2件（goal_manage → memory_create） | 5件（invoke_skill×2 → memory_create → goal_manage → update_context） |
| 記録内容 | 英語・簡素・タグ規約外 | 日本語・日付付き・構造的 |
| セッションまたぎ復元 | memory_search のみ | memory_search + goal_manage list（目標含む復元） |
- 結論: free モデルはスキル探索をスキップするため検証対象として不適。**本番想定モデル（deepseek-v4-flash 相当以上）ならスキル群のクロス発動が機能**し、Phase D は成立
- 示唆: スキル発動の信頼性をモデル任せにしない余地（プロンプト補強 or ハーネス側注入）はあるが必須ではない

### 発見3: タグ規約（project:<slug>）はスキル指示だけでは守られない
- make-project を invoke しなかった場合、LLM は自由なタグを付与（free: `["project","python","sample",...]`、flash: `["decision","project"]`）
- 原因の一部: 試作スキルが config の `enabled_skills` に未登録のため、LLM が存在を認識できない（`data/skills/` 配置のみでは list_skills に出ない）
- **設計変更: R3 に「サーバー側タグ強制」を追加**（Phase B で検討）:
  - 案A: memory_create ツールが `project:<slug>` を自動付与（dev persona のみ・source_context 等から slug 解決）
  - 案B: タグ検証（`project:<slug>` 必須・規約外は補正 or 拒否）
  - スキル指示に頼る現行案では V4（プロジェクト分離）が保証できないため、サーバー側強制が必須

### 発見4: サーバー自動抽出がバックアップとして実効
- 明示的な記録指示でも tool_call しないケースがあったが、MemoryLLM の自動抽出（auto_captured）が記録をカバー
- 「スキルが書かない」層を自動抽出が担保 → 設計のバックアップ層は有効。二重記録は類似度>0.85 ガードで緩和

### 発見5: 応答品質
- flash は明示指示なしでも日本語・マークダウン構造化で応答。free は英語・簡素
- 「記録しておいて」指示でも tool_call 0件のケースあり（free）→ スキル駆動の信頼性はモデル依存（発見2 と同根）

### 設計書への変更（本節による反映）
- R3: 「サーバー側タグ強制」を追加（発見3、Phase B で具体化）
- V4: 検証方法に「スキル経由 + サーバー側タグ強制の両経路で確認」を追加
- Phase D: 新規スキルの `enabled_skills` 登録を必須手順に追加（発見3、config.json の enabled_skills 更新）
- 制約: evolution バグ修正（e7354bd1）が main に反映済みのため、本設計の前提に含める

---

## 実装結果（Phase A、2026-08-14）

### A1: セッション終了フック（R1+R2）— 完了
- **実装**: `nous/api/http/routers/events.py` — ingest の publish 後に `raw_events` に `type == "session.stopped"` があれば fire-and-forget（`asyncio.create_task` + `add_done_callback` で例外ログ）で `_summarize_session_end` 起動。`_session_manager.get_or_create(persona, session_id, db=...)` → `window.get_active_path()` を turns 化 → `summarize_and_store(ctx, config, turns)`（`tags=["session_summary"]`, importance=0.65）。`contextlib.suppress(Exception)` で非致命化。空ウィンドウはスキップ
- **検証**: `tests/unit/test_session_stop_hook.py` 新規 5 passed（サマリ生成/空スキップ/config 失敗 suppress/有無で起動判定）。回帰: test_plugin_auth 8 passed
- 二重ガードは Phase A 最小実装（空リストスキップ + 類似度>0.85 依存）。重複観測時は「サマリ済み境界」を追加

### A2: memory_search sort="updated_at"（R4 読み取り手段）— 完了
- **実装**: `SearchQuery.sort` 追加（engine.py）→ `SearchEngine.search()` 末尾で `updated_at` 降順ソート（post-filter 後・全モード共通）。`_tool_memory_search` / `tools.py` / `definitions.py` に `sort` パラメータ追加。`docs/llm_usage_guide.md` に使用例追記
- **検証**: `tests/unit/test_search_engine.py` +2（updated_at 降順 / sort=None で従来動作維持）。36 passed。V9 を満たす: `memory_search(tags=["session_summary"], top_k=1, sort="updated_at")` は最新1件のみ
- 注意: hybrid は top_k で切った後にソートされる（top_k=1 + sort で「最新1件」は成立）。レスポンス JSON に updated_at は含まれない（従来仕様）

### 次フェーズ
- Phase B（R3+R4+R7）: ユーザー確認必須（dev persona 運用 + .agent/ 廃止 + サーバー側タグ強制）
- Phase C（R5 get_context 改善）→ Phase D（スキル再編成 + enabled_skills 登録）
