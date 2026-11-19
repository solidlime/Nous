# ハードコード棚卸しとコンフィグ化 — ダッシュボード対応

date: 2026-11-20 / 改訂: 同日（ルアン・メェイ PLAN 審査 BLOCK 対応）
status: 実行済み（2026-11-20 — Phase 0〜4 全完了。コミット: ad271a2 / 151bbba / 16410c2 / Phase 2 8コミット / Phase 3 4コミット (62007d5, 7dcd19c4, 6c08e497, c6bd9046, 020e1fc6) / fix-js 4コミット）
由緒: らうらう依頼「nous全般のハードコードにすべきでない部分の棚卸しとコンフィグ化。ダッシュボードでコンフィグできるように改修」

## 決定記録（2026-11-20 らうらう + 審査後修正）

- **実装範囲: Phase 0（基盤）+ Phase 1〜4 全部**
- **D4-1 重複閾値の統一既定: 0.85 据え置き**〔審査 #7 で 0.75→0.85 に修正。理由: 両閾値は概念が同じでも校正母集団が別（write_service=manifest エントリ、hooks=スキル）。実測 fixture（最高 0.8589 / 次点 0.3626）は 0.75/0.85 を判別できない =「反例が出ない」は「同値でよい」の証明にならない。らうらう回答の 0.75 は撤回し 0.85 で出荷、hooks 側に 0.75〜0.85 境界ペアの fixture を足して判別可能にする〕
- **workers カテゴリ: 動的読みに改修**（worker ループ内で get_settings() を動的参照。`proactive_worker.py:68` の既定引数 `interval_seconds: int = DEFAULT_INTERVAL_SECONDS` は None 既定に変えループ内解決）
- BUILTIN_PROFILES: プリセット残置 + ドリフト警告（サーバ側 /api/chat/config/defaults を単一の真実にし、JS に数値を再ハードコードしない。警告は初回 or 明示ボタン時のみ — 毎回出ると読まれない）
- **llm カテゴリは新設しない**〔審査 #3: 既存 `Settings.memory_enrichment: LLMConfig` と同形の2つ目のモデルが生え、env 接頭辞 NOUS_LLM__* と NOUS_MEMORY_ENRICHMENT__* が割れて本番 compose が壊れる。→ memory_enrichment 属性へ Field 追加、SETTINGS_META の表示名を "LLM (補助)" にする。LLMConfig 改名は AliasChoices 互換の独立タスク〕
- **tools カテゴリは新設しない**〔審査 #9: Phase 2 時点で approval_timeout_seconds 1キーのみ = 最小限主義に反する。→ general へ。Phase 3 で3キー以上集まるならその時新設〕
- **search.mcp_recency_weight は search に置く**（payload 上限は mcp でも、重みは検索エンジンの性質。mcp に寄せない）
- recency λ: dangerous 扱いは**しない**〔審査 Q5(b): dangerous は認証ゲートであって安全ゲートではなく、api_key 空の既定では no-op、UI に dangerous 概念も無い。→ 通常キー + tier: expert〕
- **統一原則（らうらう追加指示「統一できる設定は統一しておいて」）**: 同一概念の分散は1キーへ統合。ただし **「概念が同じでも校正母集団が違う」を第3カテゴリとして扱う**〔審査 #7〕: 1キー化する場合は既定値は動かさず、判別 fixture を先に用意する。「概念違いの同値」は統一しない（承認 120s vs シェル 120s）。
- **Settings.silence_hours → session_silence_hours に改名**〔審査 #11: サーバ UI とペルソナ UI に同名 silence_hours が出るのは操作事故の元。AliasChoices("session_silence_hours", "silence_hours") で旧 env 互換を保持。使い側 session_events.py:34 も更新〕

## Phase 0 — 基盤コミット（審査 BLOCK の解除条件。最優先・単独コミット・私が実装）

審査 #1〜#3: 現状 `main.py:187 settings = Settings()`（A）と `get_settings()` の lru_cache（B）が別インスタンスで、RuntimeConfigManager の setattr は B にしか効かず全 `ctx.settings`（A）に届かない。Phase 2 の約110キーが「保存されるが効かない」まま出荷される。これを先に直す:

1. **インスタンス同一化**: `main.py:187` を `settings = get_settings()` に。AppContextRegistry.configure(settings) 配下の全 ctx.settings が RCM の setattr 先と同一になる。
2. **起動時 overrides 適用**: RuntimeConfigManager に `apply_overrides_to_settings()` を追加し、main 起動時に1回呼ぶ。非 hot キー（cors/plugin 等）が再起動で反映される（現状は overrides ファイルに保存されるだけ）。**Phase 2 の受け入れ条件「再起動で反映される」の保証**。
3. **型検証**: Settings のサブモデル（BaseModel 側のみ、Settings トップは除く — 起動時代入を弾かないため）に `validate_assignment=True`。`admin.update` は ValidationError → HTTP 400（現状 pydantic 検証ゼロ、`"0.75"` 文字列がそのまま setattr されて `item.score >= threshold` が TypeError）。
4. **api_key 未設定時の書き込みガード**〔審査 #8〕: `general.api_key` 空（開発既定で _require_admin 素通り）のとき、cors / plugin / api_keys カテゴリの PUT を 403 で拒否（CORS * にされる攻撃面遮断）。
5. **読み手の統一**: overrides を Settings へ適用する設計なので、使い側は `get_effective_value` でなく **`settings.<sub>.</key> の直接読み**に統一する（env も overrides も pydantic が解決済みの値が手に入る。get_effective_value は UI 表示用に残る）。env 枝が生文字列を返す非対称問題（審査 #2a）も同時に解消。

**Phase 0 検証（審査指定の3テストを新設）**:
- `test_hot_reload_reaches_ctx_settings`: RCM().update("search","recency_lambda",1.2) → AppContextRegistry の settings.search.recency_lambda == 1.2（今日は fail するはず = 審査 #1 の証明）
- `test_override_type_coercion`: POST /api/settings {"category":"memory","key":"duplicate_threshold","value":"0.75"} → float 0.75 / 不正型は 400（500 不可）
- `test_restart_applies_overrides`: Settings 再構築相当で non-hot override が反映
- 既存全テスト緑 + test_config_defaults.py の lock-in 更新（**担当: Lane 1 私。キー追加のたび必須**）

## 実装編成（審査 #4 反映 — 所有権の空白と重複を解消）

**Phase 0 + Lane 1（私・単独）**: main.py / admin.py〔審査で無所有者だった2点を私に確定〕/ settings.py / runtime_config.py / settings-ui.js カテゴリ定義 / chat_config.py・session_config.py・tool_config.py・compression_config.py / chat_management.py（_field_tier / _field_section / _is_secret_field）— **基盤コミット→テスト緑を確認してから並列レーンを起動する**（並列中にキー名が動くと全レーンが存在しないキーを参照して全滅する）。

並列レーン（基盤コミット後に起動。所有権はファイル単位で排他）:
- **fix-js**（先行稼働中 — Phase 0 とファイル非接触のため）: Phase 4 JS 単一ソース化 + 不整合統一。settings-save.js の RELOAD_CATEGORIES も fix-js 所有（restart カテゴリ追加が決まったら Lane 1 から追指示）
- **fix-memory**: write_service.py / hooks/memory_extraction.py / evolution_service.py / mot_thoughts.py / cue.py
- **fix-timeout**: openai_compat.py / mcp_client/* / approval.py / voice/irodori.py / routers/media/tts.py
- **fix-workers**: wiki_worker.py / proactive_worker.py / activity_worker.py / prospective_worker.py / schedule.py〔time_utils.py は触らない〕
- **fix-search**: engine.py / _tools_memory.py / definitions.py / wiki/search.py / **time_utils.py（単独所有 — 審査 #4c の二重所有解消）**
- **fix-aux**: 補助 LLM マップ適用側（summarizer 群 / character_judge / pattern_detector / session_notes など）
- **fix-chat-usage**: ChatConfig 追加 Field の使い側（response_validator / context_loader / pipeline）

## 0. 目的とスコープ

コードに埋め込まれた調整値・接続先・閾値を、既存のコンフィグ基盤（Settings + ChatConfig）へ外部化し、WebUI ダッシュボード（Settings タブ / Chat 設定パネル）から編集可能にする。やらないことは §6（D5/D6）。

## 1. 既存基盤（実装の前提）

### サーバ共通設定: Settings + SETTINGS_META
- `nous/config/settings.py` — pydantic Settings。カテゴリ: general（Settings 直下属性）/ server / mcp_security / embedding / reranker / search / qdrant / memory_enrichment / wiki / cors / irodori / plugin + api_keys 群。
- `nous/config/runtime_config.py` — `SETTINGS_META`: (category, key) → SettingMeta(label, hot_reload, restart_note?, reload_time?)。`RuntimeConfigManager`: get_effective_value（UI 表示用）/ update（setattr + overrides 永続化）。**Phase 0 以降、読み手は settings 直接読み**。
- `nous/api/http/routers/admin.py` — GET/PUT /api/settings。Phase 0 で ValidationError→400 と api_key 未設定ガードを追加。
- フロント `features/settings/settings-form.js` — SETTINGS_META 駆動の動的フォーム。`settings-ui.js` の CATEGORY_ORDER / CATEGORY_ICONS / CATEGORY_DESCRIPTIONS に新カテゴリを足す。

### hot_reload 判定基準（審査 Q2 で3点化 — これに従う）
1. 使い側が**毎回**読む（get_settings() または保持サブオブジェクト）→ **True**。ただし同一 Settings インスタンスであることが前提（Phase 0 で担保）。
2. 消費側が **1つでも**起動時コピー / 初期化時焼き込みを含む → **False**（「一部の消費側だけ動的」は hot と言えない。典型: memory_enrichment.* は _init_brain_llm が焼き込む / general.log_level は setup_logging 起動時1回 / general.data_root は自己破壊の対象外処理）。
3. 周期的にしか読まれない（enabled / interval）→ **True** だが reload_time に「次サイクル（≤ interval）」を必ず書く（settings-form.js は既に meta.reload_time をツールチップ描画済みで新規実装不要）。

### persona 毎設定: ChatConfig + _field_tier
- `nous/domain/config/chat_config.py` + `chat_management.py` の `_all_flat_fields()` が UI API を駆動。
- **ChatConfig に Field を足すときの登録3点（審査 #10 — 全追加キーで必須）**: `_field_section`（未登録は "core" に落ちる）/ `_field_tier`（未登録は expert → 既定表示から消える）/ `_is_secret_field`（secret を足す場合のみ）。

## 2. 棚卸し総覧（72 Python + 67 JS → 分類）

| 分類 | 意味 | 対応 |
|---|---|---|
| **D1** | 設定クラスに存在するが SETTINGS_META 未登録 | SETTINGS_META 追加のみ |
| **D2** | 完全ハードコード（設定が存在しない） | Field 追加 + 使い側変更 |
| **D3** | サーバ既定値の JS 側複製 | defaults API / _defaultOf() 経由へ |
| **D4** | 同一概念の値が複数箇所で不揃い | 設定化と同時に一本化（校正母集団が違うものは既定据え置き） |
| **D5** | 意図的固定値（ドメイン定数・UI 気分値） | 変更しない。記録のみ |
| **D6** | 外部化が望ましいが別タスク規模 | 今回やらない |

### D1: SETTINGS_META 未登録の既存設定（Phase 1 対象）

| category | key | hot_reload | 備考 |
|---|---|---|---|
| wiki | enabled, interval_seconds, run_at_hour, topics_per_cycle 等 ~28 key | True（worker が動的読み）+ enabled は reload_time「次サイクル」 | journal activity 作業（#110 未コミット分）と名称突合 |
| wiki | provider, api_key, model, base_url | 呼び出し時構築なら True。実装時1つずつ確認 | secret マスク |
| search | rerank_enabled / injection_max_bm25 | True | dict は JSON text 入力 |
| cors | allowed_origins 等 4 key | **False**（起動時ミドルウェア）restart_note + api_key 未設定時 read-only | |
| plugin | enabled, api_key | **False** + 同上ガード | secret |
| memory_enrichment | enabled, provider, api_key, model, base_url | **False**（_init_brain_llm 焼き込み）〔審査 #5 で True→False 修正〕restart_note | 表示名 "LLM (補助)" |
| irodori | url, voice, model, timeout_seconds | 呼び出し時なら True。実装時確認 | advanced は ChatConfig 側と二重 → 出さない |
| general | session_silence_hours（旧 silence_hours） | True（session_events.py 動的 getattr） | 改名は Phase 0 |
| api_keys | anthropic/openai 等 5 key | use_cases.py:257 が動的読み。**Phase 0 ガード対象**。get の表示は RCM 経由で見える化 | secret |
| explorer | — | **対象外**（読むコードが無い。削除は別カード） |
| general | data_root / log_level / contradiction_threshold | **対象外**（data_root は移動事故 / log_level は setup_logging 起動時焼込 / contradiction_threshold は未読死設定 — **SETTINGS_META には登録しない**〔審査 #6〕。Field は env 互換で残し docstring に deprecated） |

### D2: ハードコード → 設定化（Phase 2/3 対象）— 優先度「高」

| # | 場所 | 現値 | 移し先 | 備考 |
|---|---|---|---|---|
| 1 | hooks/memory_extraction.py:47 | 0.85 | memory.duplicate_threshold | D4-1 統一（既定 0.85） |
| 2 | write_service.py:21 | 0.75 | memory.duplicate_threshold | 同上（0.75→0.85 に変わる。判別 fixture を hooks 側に先行追加） |
| 3 | mcp_client/http_client.py:41,73 + stdio_client.py:43,67 | 30s×4 | mcp.request_timeout_seconds | |
| 4 | openai_compat.py:125 | 60s | memory_enrichment.timeout_seconds〔llm→修正〕 | 低速プロバイダで詰まる筆頭 |
| 5 | openai_compat.py:44-52 vision model リスト | gpt-4o 等 | memory_enrichment.vision_models〔同上〕 | |
| 6 | approval.py:17 | 120s | general.approval_timeout_seconds〔tools→修正〕 | shell_timeout(120) と同値偶然 — 統合しない |
| 7 | voice/irodori.py:21 | 3 | irodori.retry_count | |
| 8 | wiki_worker.py:133,152 | 60s/1800s | wiki.worker_retry_seconds / worker_error_retry_seconds | |
| 9 | proactive_worker.py:44 | 1800s | workers.proactive_interval_seconds | None 既定 + ループ内解決〔審査 Q2〕 |
| 10 | schedule.py:48 | 3 | ChatConfig(tool_config).schedule_fail_limit | _field_section/tier 登録必須 |
| 11 | time_utils.py:11 | λ=0.5 | search.recency_lambda〔search 確定〕 | tier: expert |
| 12 | session_notes.py:30 | 6.0h | ChatConfig(session_config) | session_silence_hours（Settings）と概念違い — 命名で区別 |
| 13 | wiki_worker.py:64 | 3 | wiki.min_topic_memories | |
| 14 | evolution_service.py:22,28,29 | 0.9/0.85/0.95 | memory.corroboration_min / interference_min / interference_max | |
| 15 | memory_extraction.py:54 | 8192 | memory_enrichment.extraction_max_tokens〔llm→修正〕 | コスト直結 |
| 16 | mot_thoughts.py:23-27 | 0.8/3/0.5/72h | memory.mot_* 4本 | |
| 17 | activity_worker.py:49 / prospective_worker.py:55,57 | 3600s/30s | workers.activity_interval_seconds / prospective_* | ループ内動的読み |
| 18 | irodori.py:150 + tts.py:729 | 5s×2 | irodori.health_timeout_seconds | **同一概念確定（2026-11-20 実測: 両者とも GET /v1/models 疎通確認の httpx タイムアウト。tts.py 側は IrodoriClient.health_check() の重複実装 → 委譲に改修）** |

優先度「中」（Phase 3）: 補助 LLM の temperature/max_tokens 12+7 箇所 → memory_enrichment.aux_* マップ / プロンプト材料文字数上限群 → ChatConfig(compression_config) / wiki 系文字数 / MCP payload 上限 9 値 → mcp / cue.py → memory / places.py → general / 検索系小項目。

### D3: JS 側のサーバ既定複製（Phase 4 対象 — fix-js 稼働中）
- apply.js / apply-groups.js / save.js のフォールバック直書き約25値 → `_defaultOf()` 経由
- chat-attachments.js:13 MAX_ATTACHMENT_BYTES → サーバ配信値（Field が無ければ Lane 1 で追加）
- BUILTIN_PROFILES → ドリフト警告（初回 or 明示ボタン時のみ）
- turn.js:84 の 80px と chat-tools.js:195 の 100px → 100px に統一
- その他: 画像プロンプト切り詰め重複、SEARCH_LIMIT=20、perPage:20、800ms/500ms

### D4: 不揃いの一本化（Phase 2 に同梱）
1. **重複記憶閾値**: memory.duplicate_threshold 既定 **0.85**（判別 fixture 先行）。general.contradiction_threshold は docstring deprecated。
2. **MCP 検索重み**: chat 面と MCP 面は設計意図の可能性 → 一本化しない。MCP 面は search.mcp_recency_weight へ。
3. **要約 prompt 二重管理**: pipeline/summarizer.py と summarizer.py（英/日）→ 使用実態確認し死んでいる方を削除。
   - **実測で前提が外れた（2026-11-20 fix-aux レーン）**: 両方とも生きている。A=pipeline/summarizer.py は予算超過時に古いメッセージを要約し system prompt へ注入、B=summarizer.py は退避/終了ターンをペルソナ一人称で要約し記憶に保存。トリガ・出力先・本文がすべて別で統合対象外。日英ペアは ADR-001 で既に解消済み。実処置は compress.py:8 の死んだ再エクスポート削除（importer ゼロ）のみ。
4. **ヘルスチェック**: irodori 2箇所は同一概念（#18 へ統合）。image_gen/health.py:18=3s は別リソース → 既存 imagegen 設定があればそこへ、無ければ D5 扱いとし混ぜない。

### D5: 意図的固定値（変更しない — 記録のみ）
schedule.py _WHEN_UNITS、recurrence 写像、ポート範囲 1-65535、SSE バックオフ、UI デバウンス群、グラフ描画上限、token_counter.py のモデル→context 長表（外部 JSON 化は将来課題）。

### D6: 将来課題
プロンプト文字列のファイル化（13定義 → prompts/ + prompt_dir。独立タスク）、token_counter 外部 JSON 化、sandbox_manager docker CLI タイムアウト群、explorer / memory_links 死設定掃除、convo_importer CLI オプション化。

## 3. 実装 Phase 分け

- **Phase 0 — 基盤コミット**（§冒頭に記載。単独コミット、3テスト付き、テスト緑が並列起動の条件）
- **Phase 1 — D1 の SETTINGS_META 登録 + settings-ui.js**（Phase 0 の後、私が実装。危険カテゴリ（qdrant/embedding）と安全キーをスクロール順で混ぜない〔審査 Q1〕）
- **Phase 2 — D2 高 + D4**（基盤コミット後、6レーン並列）
- **Phase 3 — D2 中**（Phase 2 の枠組みに乗せる追加作業）
- **Phase 4 — D3 の JS 単一ソース化**（fix-js 先行稼働中）
- Phase 5 — プロンプトファイル化（将来・独立計画書）

## 4. 設計判断の記録

- **Settings か ChatConfig か**: ペルソナ毎に変える意味があるか（応答体裁・感情系）→ ChatConfig。サーバ全体（タイムアウト・接続先・周期）→ Settings。
- **既定値は現行値**: 設定化で挙動が変わらないことを原則とする（D4-1 の 0.75→0.85 問題は審査で「判別不能なら現行 hook 側 0.85 を据え置く」に決着）。
- **カテゴリ新設は memory / mcp / workers の3つのみ**（llm・tools は審査で却下。Phase 3 で tools 系が3キー以上に育てば再検討）。
- **使い側は settings 直接読みに統一**（Phase 0 の設計。get_effective_value は UI 表示用）。

## 5. 検証計画

- Phase 0: 審査指定3テスト（hot_reload_reaches_ctx_settings / override_type_coercion / restart_applies_overrides）+ 全既存テスト緑
- 単体: SETTINGS_META 追加分の lock-in 更新（test_config_defaults.py — Lane 1 担当）、ChatConfig 追加分が flat fields に現れること、使い側の回帰（既定値で挙動不変）
- E2E: Settings タブに新カテゴリが出る・保存・再読込で戻る。restart_note 表示。**再起動で non-hot 変更が反映される**
- ゲート: pytest / ruff / mypy new-0 / npm test

## Open questions（解決済み）

1. D4-1 既定値 → **0.85 据え置き + 判別 fixture 先行**（審査 #7）
2. BUILTIN_PROFILES → **警告表示（初回 or 明示時のみ）**
3. workers → **動的読みに改修**（None 既定 + ループ内解決）
4. recency λ → **通常キー + tier: expert**（dangerous は認証ゲートで使う概念）

## Phase 3 完了記録（2026-11-20）

- mot_top_k 配線漏れ修正 + stale コメント更新: 62007d5
- 添付上限 10MB を ChatConfig.max_attachment_bytes に統一（サーバ判定・JS 参照・テスト基準の三点一本化）: 7dcd19c4
- 要約プロンプト文字数上限を CompressionConfig 化（summarize_message_max_chars / summarize_target_chars）: 6c08e497
- journal_activity.py の ChatConfig 廃止系・emotion_decay.py の Settings λ 廃止系・wiki_journal.py 未使用引数: c6bd9046, 020e1fc6
- core/constants.js 恒久置き場: fix-js レーンが Phase 2 で先行実施（b5bde006, N.Core.UI + PER_PAGE 統一）
- aux LLM 引数マップ（character_judge 0.0/512, pattern_detector 0.3/512, summarizer 0.0/512, 256）: **Settings 化しない判断**。タスク特性由来の設計値で、SETTINGS_META のスカラー UI に合わない dict 形式。個別スカラー化は 10キー増のノイズ。専用 LLM の上限系は Settings 化済み（brain_max_tokens 等）で、残る直書きはフォールバック値とタスク固有値のみ。
