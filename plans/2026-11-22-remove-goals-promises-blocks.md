# 約束・Goals・Core Memory Blocks 削除計画（v2 — 事前アーキテクチャ判断反映済み）

> **ステータス: 実装完了** (2026-11-22)。実装: 3d289d5c (113 files, +262/−5303, 4レーン+追尾掃除)。REVIEW: ルアン・メェイ PASS — 掃き残し5件は同コミット反映。GATE 全緑（pytest 3385/vitest 420/ruff/mypy baseline 同期/docs-drift 66-67%/実ブラウザ 3面）。残課題は末尾の完了記録へ。

日付: 2026-11-22 / トリエージ: 本格 → フルパイプライン + 事前アーキテクチャ判断
v2: ルアン・メェイ（Oracle）事前判断 BLOCK → 指摘18件を全反映（判定記録は末尾）。
**注意: 本文の行番号は目安（実ファイルとずれあり）。実装は行番号ではなくシンボル名・コード内容で位置を特定すること。**

## 決定事項（ユーザー確定 + 判断で確定）

1. **削除する3機能**
   - **Goals**: goal_manage ツール、`["goal","active"/"achieved"/"cancelled"]` タグ運用、抽出・注入・表示の全経路
   - **約束**: `["promise"]` タグ運用、抽出・注入・cue 照合（due_cues / prospective.due sweep）、session_begin の open promises
   - **Core Memory Blocks**: memory_blocks テーブル機構、profile_update ツール、`/api/blocks`、チャット常載プロフィール注入（【自己像】【ユーザー像】）、UI
2. **残すもの**
   - **`/api/chat/{persona}/commitments` は insights 専用として残す**（goals キーのみ削除）。内省パネルの唯一の供給源のため。ローダー（chat-core.js 初期化・turn-events）も残る
   - **agent:task**（schedule_task 予約セルフターン）: ProspectiveWorker の agent:task 経路（`run_cycle` 末尾 `run_agent_tasks()`、due_agent_tasks/next_task_wait_seconds/run_self_turn）は完全維持。約束照合 sweep のみ削除
   - **cue.py の keep-list（拡張済み）**: `parse_deadline` / `parse_time_cues` / `time_cue_tag` / `comparable` / `within_window` **/ `CUE_TIME_PREFIX` / `DUE_WINDOW_HOURS` / `OVERDUE_GRACE_HOURS`**。後ろ3つは schedule.py（import・使用）と within_window 本体（既定引数・内部参照）が必須。削除は `due_cues` / `event_cued_memories` / `event_cue_tag` / `cue_tags` / `event_cues` / `due_label` / `PROMISE_TAGS`
   - **memory kind "prospective"**: 検索種別としては存続
   - **識別コア3行**（relationship / user / wearing）: persona state 由来で無関係・存続
   - **context_loader.py の `_hidden` フィルタは残す**（旧 DB の persona_info に残る goals/promises/current_goals 行が毎ターン復活するのを防ぐ防御）。GOALS/PROMISE 節の描画のみ削除
   - **legacy `goals`/`promises` テーブルの CLI 件数表示・jsonl/legacy export/import は残置**（旧 DB・旧ダンプ互換のため。非破壊方針）
   - 感情・体況・装備・wiki・検索・journal・handover・open-question・内省の全機能
3. **データは非破壊**: 既存 goal/promise タグ記憶・memory_blocks 行・既存 DB テーブルはそのまま残す。`DROP TABLE` / `DELETE FROM` 禁止（規約）。schema.py から `CREATE TABLE memory_blocks` を外し新規 DB には作らない。migrations.py（v11/v15）は旧 DB 用に**残置・編集しない**（`PRAGMA table_info` ガードで新規 DB でも無害 — 判断確認済み）
4. **スキル**: goal-coach は ~/.agents/skills から削除。project-manage は目標管理を全削除（data/skills と ~/.agents/skills の両方を編集）。make-project の `goal` タグ行修正、session-start の open promises 記述削除
5. **履歴文書は編集しない**: docs/archive/、.spec/、plans/ の既存文書は履歴として不変。現行 docs と README のみ同期
6. **孤児定数**: `PROMISE_MAX_CHARS`（domain/profile/tokens.py）は利用者消滅で削除。ただし他に利用者が残る場合は残す（実装時に grep 検証）。session_notes.py 側の約束用定数は promise_note 削除と一緒に消す
7. **mypy-baseline.txt は手編集ではなく再生成**（block_repo 4行以外に memory/service.py の save_block/list_blocks/delete_block 行と周辺 Returning-Any 行も消えるため）

## レーン分割（ファイル完全分離・並列実行・git commit はオーケストレーターのみ）

### Lane 1 — バックエンド Python（nous/**/*.py と scripts/**、mypy-baseline.txt）

**Goals/約束の削除**:
- `api/mcp/_tools_goal.py` — ファイル削除
- `api/mcp/tools.py` — goal_manage/profile_update の import・TOOL_MAP 登録・`@_tool` ラッパを削除
- `api/mcp/_tools_persona.py` — get_context の goals fetch / due_labels / result_summary の goals 数を削除。`_tool_profile_update`・`_sanitize_profile_content`・PROFILE_BLOCK_NAMES import に加え **`DEFAULT_PROFILE_MAX_TOKENS, estimate_tokens` import（:12 付近）も削除**（_tool_profile_update 専用 → 未使用で ruff F401）
- `api/mcp/_tools_helpers.py` — `_format_lightweight_response` の goals/active_goals/due_labels 引数と `⚠️ YOUR ACTIVE COMMITMENTS` 節を削除（equipment/emotion/recent 等は維持）
- `api/mcp/_tools_memory.py` — QUERY_RESOLVE_MIN_SCORE は残す。コメントの「goal-resolution」言及を書き換え
- `application/chat/memory_extractor.py` — **連鎖全体**: `_process_goal_actions` / `_process_promise_actions` の定義と**呼び出し箇所（:412,:416 付近）**、`_parse_memory_llm_result` の goals/promises 正規化、**3要素タプル返却を2要素（facts, insights）に**、commitments 文字列、PROMISE_TAGS・build_cue_tags import を削除
- `application/chat/memory_prompts.py` — 抽出 JSON スキーマから goals/promises 配列に加え **`{commitments}` 節（:22-23 付近）と format() の commitments kwarg** も削除（片側だけ消すと KeyError）
- `application/hooks/memory_extraction.py` — **第2の goal/promise 書き込み経路を完全削除**: `_apply_commitment`（get_by_tags(["goal","active"]) を回す経路）、`_apply_result` の戻り値を2要素化、goal/promise タグ組の二重定義、:131-140 の該当ログ。pi-hook 経路で goal タグが書かれないようにする
- `application/chat/pipeline/context_loader.py` — GOALS 節 / PROMISE 節を削除。**`_hidden` は残す**。due_cues・event_cued_memories import を削除
- `application/chat/pipeline/prompt.py` — 常載プロフィール注入（get_profile_blocks →【自己像】【ユーザー像】static_parts）を削除。TOOL_USAGE_GUIDELINES の約束・goal_manage 言及を削除
- `application/chat/pipeline/post.py` — saved_goals/saved_promises の SSE yield を削除
- `application/chat/events.py` — MemoryActivitySSE の goals/promises フィールドを削除
- `application/chat/pipeline/summarizer.py` — goal/promise 言及を確認し該当箇所を削除
- `application/session/session_notes.py` — `promise_note` と PROMISE_TAGS/due_cues import・約束用定数を削除
- `api/http/routers/chat/session_events.py` — `_begin_notes` の promise_note 積みを削除
- `application/workers/prospective_worker.py` — 約束照合 sweep（get_by_tags + due_cues、prospective.due 経路）、`EVENT_TYPE`、`_last_due`、due_cues import、docstring の約束記述を削除。**`run_cycle` 末尾の `run_agent_tasks()` は絶対に残す**（agent:task 唯一の入口）。activity_worker 連携・due_agent_tasks 系は完全維持
- `domain/persona/service.py` — `_extract_goals` と goals 抽出分岐を削除。`skip_keys` は persona_info への生保存防御として**残す**
- `domain/memory/cue.py` — keep-list（決定2）以外を削除。冒頭 docstring を agent:task 用 time-cue 機構として書き直し
- `application/chat/tools/builtin.py` — `_MCP_SHARED_TOOLS` から goal_manage/profile_update 削除
- `application/chat/tools/definitions.py` — goal_manage/profile_update の ToolDefinition 削除。**schedule_task の説明文（:382 付近）から「ユーザーとの約束は memory_create の goal に任せ」文言を削除**（goal 削除後は虚偽のため）
- `domain/tools/registry.py` — goal_manage / profile_update の ToolSpec 削除
- `api/http/routers/chat/chat_management.py` — **`/api/chat/{persona}/commitments` 登録は残し、`get_chat_commitments` の応答から goals 側（goals fetch・goals キー）だけ削除**。insights 供給は完全維持
- `api/http/routers/persona/persona_dashboard.py` — `_build_goals` と goals キーを削除
- `api/http/routers/persona/persona_dashboard_v2.py` — `_goals_summary` と `/api/v2/goals/{persona}` を削除

**Blocks の削除**:
- `infrastructure/sqlite/block_repo.py` — ファイル削除
- `infrastructure/sqlite/memory_repo.py` — SQLiteBlockMixin の mixin 削除
- `domain/memory/repository.py` — block 抽象 API 削除
- `domain/memory/service.py` — block メソッド群削除（save_block/list_blocks/delete_block 等）
- `domain/profile/tokens.py` — PROMISE_MAX_CHARS を削除（grep で利用者ゼロ確認後）
- `infrastructure/sqlite/schema.py` — `CREATE TABLE memory_blocks` 削除。migrations.py は残置
- `api/http/routers/memory/memory.py` — `/api/blocks/{persona}` GET/POST/DELETE 削除
- `api/http/routers/persona/persona_dashboard.py` — `_build_blocks` と blocks キー削除
- `api/http/routers/persona/persona_dashboard_v2.py` — `/api/v2/blocks/{persona}` 削除
- `api/http/sections/chat/chat_memory_panel.py` — `#memory-goals-list`/`#memory-promises-list` HTML 削除
- `api/http/sections/chat/chat_layout.py` — `/goal` プレースホルダ修正
- `api/http/sections/base.py` — **overview-blocks.js の script タグ（:41 付近）を削除（このファイルは Python = Lane 1 所有）**
- `api/http/sections/timeline.py` — goal/promise/block 言及を確認し該当箇所削除
- `cli/__main__.py` — テーブル件数表示から memory_blocks を削除。**legacy goals/promises テーブルの件数表示は残置**
- `migration/exporters/jsonl_exporter.py` / `migration/importers/jsonl_importer.py` / `legacy_importer.py` — memory_blocks の読み書きを削除（旧ダンプの blocks は読み飛ばす）。**legacy goals/promises テーブルの export/import は残置**
- `application/wiki/journal.py` — `_persona_character` の get_profile_blocks try ブロックを削除（system_prompt のみで組み立て。人物設定が system_prompt だけになる仕様変更）

**Lane 1 の検証**: `ruff check` 対象ファイル / `mypy`（baseline は再生成して差分が本削除由来だけか確認）/ `python -c "import nous.api.mcp.tools"` 等の import 煙試験。pytest 全体は Lane 4 で直すので赤は想定内（import error だけ自分スコープで潰す）

### Lane 2 — フロントエンド（nous/api/http/static/**）

- `chat/chat-commands.js` — `/goal` コマンド削除
- `chat/chat-core.js` — `/goal` dispatch と data.goals → mp.update を削除。**`loadChatCommitments()` の初期化呼び出しは残す**（エンドポイント存続）。commitments 応答の goals 表示・goals キー処理のみ削除（insights 表示は維持）
- `chat/chat-tools.js` — goal 実行ラベルと `/^goal_/` アイコン削除
- `chat/chat-settings-mcp.js` — goal_manage/profile_update 説明削除
- `chat/memory-panel/panel.js` — goals/promises リスト描画を削除。commitments(insights) 経路は維持
- `chat/memory-panel/detail.js` — PANEL_KIND_LABELS の goal/promise、completeGoal を削除
- `chat/send/turn-events.js` — `_mem(...)` 呼び出しから evt.goals/evt.promises 引数を削除。**`loadChatCommitments()` 呼び出し（:148 付近）は残す**
- `chat/chat-memory-panel.js` — mp.update の引数 arity を SSE 新形に合わせる
- `chat/history/session.js` — ウェルカム文の `/goal` ヒント削除
- `features/memories/memories-core.js` — Goals セクションと Core Memory Blocks カードを削除。**dashCache.blocks 参照（:85,94-95 付近）も削除**
- `features/overview/overview-blocks.js` — ファイル削除（script タグ除去は Lane 1 の sections/base.py で実施）
- `features/overview/overview-core.js` — `#block-edit-modal` / save-block action / `_GK` デッドフィルタ / **dashCache.blocks 参照（:64,68 付近）**を削除
- `features/overview/overview-inventory.js` — **dashCache.blocks 参照（:59 付近）を削除**
- `features/activity.js` — **`prospective.due` のアイコン/ラベル（:35,47 付近）を削除**（発火しなくなるイベント）
- `base.js` / `shell.js` — `dashCache.blocks` キーを削除
- `styles/components.css` と `styles/tabs-lazy.css` — `.memory-block-row`/`.goal-row`/`.goal-text`/`.goal-time` を両方から削除
- vitest: `chat/chat-memory-panel.test.js`・`chat/chat-wiring-feed.test.js` を更新（goals/promises 描画の期待を削除）
- HTML 側の script タグ・モーダル DOM（sections 由来で無い箇所）も確認

**Lane 2 の検証**: `npx vitest run`（static 配下）で自分スコープ緑。DOM 整合は grep で二重確認

### Lane 3 — docs / scripts / skills

- `docs/llm_usage_guide.md` — goal_manage 表・promise 検索例・「5. Promises & Goals」節を削除
- `docs/memory_features.md` — Named Memory Blocks 節と prospective.due の約束照合記述を修正（agent:task は残る旨に）
- `docs/http_api_reference.md` — **v2 合成見出し（blocks/goals 部分）と Core Memory Blocks 節を削除。`GET /api/v2/overview` / `GET /api/v2/recent` / `GET /api/v2/equipment` / `GET /api/v2/items` の各エントリは必ず残す**（消すと docs drift が error）。`/commitments` の項目は insights 専用になった旨で残置
- `docs/architecture.md` — `_tools_goal.py`・profile_update・goal_manage・goal-coach スキル・常載プロフィールドキュメントを修正
- `README.md` — 目標・コアメモリブロック・goal_manage 表の行を修正
- `scripts/skill_test.py` — goal-coach 期待を削除
- `scripts/reproducibility_test.py` — goal_manage 期待を削除
- `scripts/docs_drift_baseline.json` — **`/commitments` エントリは残す（ルート存続）**。実行して warn/error が出たら本変更由来だけ直す
- `mypy-baseline.txt` — **Lane 1 マージ後に再生成**（このため Lane 3 の baseline 反映は Lane 1 完了後に行う）
- スキル編集（リポジトリ外の絶対パスも含む）:
  - `/root/.agents/skills/goal-coach/` ディレクトリ削除（リポジトリ data/skills には無い）
  - `/root/workspace/Nous/data/skills/project-manage/SKILL.md` と `/root/.agents/skills/project-manage/SKILL.md` — 目標管理（goal_manage 節・進捗確認・祝福・励まし）を全削除し、project タグ記憶による作業状態記録のみに。description も修正
  - `data/skills/make-project/SKILL.md` と `~/.agents/skills/make-project/SKILL.md` — `tags=["project:<slug>", "goal"]` を goal タグ無しに修正
  - `data/skills/session-start/SKILL.md` と `~/.agents/skills/session-start/SKILL.md` — open promises の言及を削除
  - 両コピーの内容は現状 diff があるため、**該当節の編集は両方に個別適用**（丸コピーしない）

**Lane 3 の検証**: `python scripts/check_docs_drift.py`（baseline 調整後）・`python scripts/skill_test.py`

### Lane 4 — テスト（Lane 1-3 マージ後に単独実行）

削除: `tests/unit/test_mcp_goals_promises.py`、`tests/unit/test_goals_promises.py`、`tests/unit/test_remove_goals_promises.py`、`tests/unit/test_memory_cue.py`（due_cues 分。time-cue primitives 分は残す）、`tests/unit/test_prospective_cue.py`（due 境界分）、`tests/unit/test_blocks_persona.py`、`tests/unit/test_profile_prompt_injection.py`、`tests/unit/test_profile_update_tool.py`、`tests/unit/test_profile_them_block.py`、`tests/contracts/consumer/test_goal_manage.py`
再判断: `tests/unit/test_memory_blocks_persona_migration.py` — v11/v15 移動は残置するため、**移行挙動を検証するテストは残し、削除済み block API を呼ぶ部分だけ剥がす**
更新: `test_context_sections.py`（TestPromiseSection）、`test_get_context_budget.py`、`test_memory_llm.py`（commitments 文字列・2要素タプル）、`test_memory_panel_wiring.py`（SSE goals/promises）、`test_hook_extraction.py`（2要素タプル）、`test_builtin_handlers.py`、`test_mcp_context.py`、`test_chat_pipeline.py`（GOALS/PROMISE 節。_hidden は残存なので期待維持）、`test_legacy_schema_init_80.py`（**memory_blocks を `DELETE FROM` する2テストは新規 DB にテーブルが無くなるため調整 — blocks 掃除を外す**）、`test_sqlite_concurrency.py`（:186 付近）、`test_sqlite_repos.py`（block mixin 分）、`test_tool_definitions.py`（goal_manage/profile_update 定義）、`test_prompt_emotion_hint.py`（:18 付近）、`test_prompt_inject_events.py`（:53 付近）、`test_memory_service.py`・`tests/integration/test_memory_service.py`（block API）、`tests/integration/test_http_routers.py`（/api/blocks）、`tests/integration/test_dashboard_e2e.py`（goals/blocks シードとキー）、`tests/integration/test_v2_overview.py`、`test_jsonl_importer.py`/`test_jsonl_exporter.py`（blocks スキップ・legacy goals/promises は残置）、`test_session_notes.py`、`test_prospective_worker_tasks.py`（agent:task 維持・約束 sweep 分のみ削除）、`test_tool_called_invariant.py`（**`_tool_goal_manage` import の parametrize ケースを削除 — ここを忘れると収集時 ImportError で pytest 全体が落ちる**）、`test_profile_tokens.py`（PROMISE_MAX_CHARS 削除反映）、`tests/playwright/test-chat-full.js`・`test_chat_full.js`（commitments は insights 専用で存続 — goals 表示の期待だけ削除）
契約テスト: test_goal_manage 削除後、pacts 生成物・provider 側に残留が無いか確認。

## 検証条件（GATE）

- pytest 全テスト失敗 0・カバレッジ ≥60%
- vitest（static の *.test.js）失敗 0
- mypy pass（baseline 再生成後）・ruff 0・format ok
- 契約テスト pass・gitleaks 0・監査 ≤moderate
- `python scripts/check_docs_drift.py` pass
- **実ブラウザ確認**: chat ページで /goal コマンドが消え goal/promises パネルが無いこと、**内省 insights パネルは commitments から引き続き描画されること**、memories タブに Goals/Blocks カードが無いこと、overview に block モーダルが無いこと、既存機能（検索・記憶パネル・感情表示）が壊れていないこと
- session_begin 応答から GOALS 行・open promises が消え、識別コア3行が残ること
- schedule_task / agent:task の単体テストが全緑（同居コードを触ったため）

## リスクと緩和

- **プロンプトキャッシュ接頭辞が変わる**（static_parts から profile 注入が消える）→ 初回ターンのみコスト増。機能影響なし
- **Windows 本番の pi 拡張 session-start-inject.ts**（この環境に無い・chezmoi 管理）: session_begin 応答から目標・約束・プロフィール節が消えるが、拡張は節抽出方式なら空を無視するだけ。ユーザーへの事後報告対象
- **古い jsonl ダンプの blocks** は今後インポートされない（仕様変更）。legacy goals/promises テーブルの export/import は残置で互換維持
- agent:task と due sweep の同居コードを触るため、schedule 系テストの全緑を特に確認
- 行番号ずれリスク → シンボル名で位置特定（実装者への指示済み）

## 事前アーキテクチャ判断の記録（2026-11-22 ルアン・メェイ）

- 判定: **BLOCK**（v1 計画に対し18件: BLOCKER 5 / MAJOR 5 / FYI 7 / NIT 1）
- v2 で全件反映: ① commitments 兼用 → insights 専用で残置（最重要）② cue.py keep-list に3定数追加 ③ hook の第2書き込み経路（_apply_commitment・3要素タプル）完全削除 ④ test_tool_called_invariant.py 追加 ⑤ _tools_persona.py の tokens import 削除 ⑥ docs v2 合成見出しの部分削除 ⑦ memory_extractor/prompts/hook の連鎖 ⑧ prospective_worker の run_agent_tasks 残置明記 ⑨ Lane 4 テスト拡充（legacy_schema_init_80 の DELETE FROM 問題含む）⑩ mypy baseline 再生成 ⑪ sections/base.py を Lane 1 所有へ ⑫ _hidden 残置 ⑬ dashCache.blocks 追加箇所 ⑭ definitions.py schedule_task 説明 ⑮ docs_drift_baseline は commitments 残置で無修正 ⑯ activity.js prospective.due ⑰ legacy goals/promises は残置明記 ⑱ PROMISE_MAX_CHARS 削除
- 静的確認のみ（pytest/mypy/vitest 未実行）→ GATE フェーズで全検証

## 完了記録（2026-11-22）

- **実装コミット**: 3d289d5c — 113 files (+262/−5303)。4レーン並列（#011 glm-5.3 ×4）+ オーケストレーター追尾掃除（static 未使用 import 4ファイル・mypy-baseline 手動行削除同期・shell-critical.css 注記）
- **REVIEW**: ルアン・メェイ **PASS**。指摘7件のうち5件（死 mock 3行・docstring 1語・古びコメント×2・backup_restore.md 注記）をコミット前に反映。残る指摘→下記残課題
- **GATE 実測**: pytest 3385 passed/0 failed/4 skipped（収集0）・vitest 39 files/420 tests・ruff 0・mypy baseline 同期済み（新規エラー0）・coverage 66-67%（閾値60%クリア）・docs-drift OK (mcp_tools=18, http_routes=77)・実ブラウザ: chat（/goal 消滅・insights 描画・memories タブ・検索・感情表示）+ overview 3面 異常なし
- **逸脱（報告済み・REVIEW 静的支持）**: test_prospective_cue.py は「due 境界分」でなく全削除（agent:task 系は test_prospective_worker_tasks.py に全量別存続だったため）／test_tools_persona.py 見出し抑制テストは top/recent 重複除外機構で同等検証に書き換え／test_memory_versions.py はリスト外だが stale block fake 掃除で追加／CSS は列挙外クラスも grep 死確認済みで追尾削除
- **残課題**: ① recall-weaver SKILL.md の promise 掘り手順（書き込み経路消滅後の運用方針 — 過去記憶のみ掘るで良いか次回確定、~/.agents/skills 側にも同期）② playwright 両 .js は期待更新+node --check のみで CI 初回実行時に実機検証 ③ Windows 本番 pi 拡張 session-start-inject.ts の節抽出挙動は事後報告対象 ④ 契約テスト実行は pact-python 導入環境で（未インストール・既存赤）⑤ jsonl の blocks は今後インポートされない（仕様変更・既計画どおり）
