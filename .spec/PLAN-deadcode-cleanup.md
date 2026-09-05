# PLAN: デッドコード削除＋配線（改訂スコープ）

日付: 2026-09-05 / 承認: らうらう（削除＋配線 改訂スコープ）
事前レビュー: #081 BLOCK → 指摘反映済み（RecallGovernor・hebbianはバッチから除外）

## スコープ外（明示的にやらない）
- hebbian_update配線: 4連成変更が必要（tool.calledへのsession_id付与 / Memoryオブジェクトlookup / memory_linksリポジトリ新設 / get_links_for_keysの永続weight読み替え）。別バッチで再スコープ
- AnthropicProvider/GeminiProvider復活: モジュールごと削除（本番はOpenAICompatProvider統一）
- contradiction.INDEPENDENT: 削除禁止（enum動的構築で生存）
- main.serve_static / nous/cli/__main__.py: 生存（保留）

## Phase 1: 削除

### モジュール丸ごと削除
- nous/api/http/sections/skills.py
- nous/api/http/sections/chat/chat_attachments.py / chat_modals.py / chat_scripts.py
- nous/domain/persona/relationship_decay.py
- nous/domain/memory/mental_model.py（+ tests/test_mental_model.py、re-exportがあれば除去）
- nous/domain/memory/recall_governor.py（+ tests/test_recall_governor.py、nous/domain/memory/__init__.py:7のre-export除去）
- nous/infrastructure/llm/anthropic.py / google.py（test_llm_reasoning / test_llm_vision のうち当該provider専用部分を削除・compat providerのテストは残す）

### シンボル削除（本番コード）
- chat/tools/builtin.py: `_handle_context_update`
- chat/tools/registry.py: `add_skills_info`
- chat/tools/definitions.py: `CONDITIONAL_TOOLS`
- event_bus.py: `subscriber_count`（定数群CHAT_MESSAGE等は**削らない**——Phase 2で配線する）
- domain/memory/repository.py: `get_goals` / `get_promises` / `find_by_tags` / `get_all_tags`
- infrastructure/sqlite/memory_crud_repo.py: `find_by_tags` / memory_stats_mixin.py: `get_all_tags`
- domain/memory/service.py: `read_block` / `get_smart_recent` / `get_relationship_highlights`
- domain/memory/memory_link.py: `hebbian_update`（git履歴に残る。将来バッチで再設計）
- domain/memory/contradiction.py: `EmbeddingProtocol`（INDEPENDENTは残す）
- domain/memory/sudachi_extractor.py: `extract_accurate`
- domain/memory/value_objects.py: `MemoryKey` / `Importance` / `Emotion` / `PrivacyLevel`（normalize_*関数群は残す）
- domain/persona/repository.py: `get_state_history` / `get_user_info` / `get_persona_info` + sqlite/persona_repo.py の同名実装
- domain/shared/result.py: `and_then` / `or_else` / `map` / `unwrap` / `unwrap_or`（Success/Failureクラスと.value/.is_okは残す）
- domain/skill.py: `list_all`
- domain/search/engine.py: `best_search_mode`
- domain/search/context_snapshot.py: `to_text`
- domain/equipment/service.py: `get_equipped_item_descs`
- infrastructure/llm/cache_utils.py: `should_add_cache_control` / `get_cache_extra_body`（build_*系は残す）
- infrastructure/llm/memory_enricher.py: 同期`enrich()`（enrich_asyncは残す）
- infrastructure/mcp_client/types.py: `list_from_claude_config` / `to_claude_json`
- infrastructure/sqlite/base_repo.py: `_execute_query` / `_execute_single` / `_execute_write`
- infrastructure/sqlite/equipment_repo.py: `list_items` / `get_history`
- infrastructure/sqlite/session_event_repo.py: `delete_by_session`
- infrastructure/tools/tool_vector_store.py: `delete_all`
- infrastructure/embedding/model.py + reranker.py: `unload()`（reload_modelは残す）
- infrastructure/image_gen/factory.py: `get_image_gen_provider`
- chat/session_window.py: `SessionWindow`クラス（`_expand_segments`はtree_session.pyがimportするため**必ず残す**）
- chat/session_store.py: `SessionWindow = TreeSessionWindow`エイリアスとchat_service.pyの死んだ再export（drive-by指摘分）

### テスト削除・更新
- 上記シンボル専用テストを削除: test_chat_service.py（update_message/truncate_to/get_message_by_id/delete_message部分）, test_tool_definitions.py（CONDITIONAL_TOOLS部分）, test_event_bus.py（subscriber_count部分）, test_memory_repo_extra.py, test_mcp_context.py（Mock設定の当該3メソッド）, test_memory_links.py（hebbian_update部分）, test_memory_entities.py（value_objects部分）, test_sudachi_extractor.py（extract_accurate部分）, test_result.py（map/unwrap/unwrap_or/and_then/or_else部分）, test_skill.py（list_all部分）, test_search_engine.py（best_search_mode部分）, test_context_snapshot.py（to_text部分）, test_sqlite_repos.py（list_items部分）, test_equipment_service.py（get_history fake）, test_session_event.py（delete_by_session部分）, test_image_gen_providers.py（factory部分）, test_decay_worker.py（stop部分→Phase 2でEvent化テストに置換）
- tests/integration + unit の `close_all` 使用は**残す**（Phase 2で正式shutdown機構になるため）

## Phase 2: 配線（#081指摘の前提修正込み）

### 2a. graceful shutdown
1. **worker停止機構の修正**（#081指摘#2）: consolidation_worker / decay_worker / context_snapshot_worker のループを `time.sleep(interval)` → `threading.Event().wait(interval)` に置換。`stop()`は `event.set()` + `join(timeout)` を提供
2. **worker参照の保持**（#081指摘#1）: create_app()で生成したConsolidation/SnapshotWorker、AppContext生成時のDecayWorkerを参照保持（AppContext属性 or モジュールレベルregistry）。**shutdown配線はmain()側に置き、create_appには参照保存のみ**（#081指摘#5・既存のworkerスレッド漏出は既存バグとして本バッチでは新規配線経路だけ正しくする）
3. **main()のシャットダウン**（#081指摘#3・Q3）: FastMCP v2にlifespanパラメータは無い。`mcp.run()`をやめ、`app = mcp.streamable_http_app(json_response=True, stateless_http=True)` + `uvicorn.Server(uvicorn.Config(app, host, port))` + `asyncio.run(server.serve())`、`finally`で `_shutdown()`: worker停止→join(timeout=5)→`asyncio.run(close_all_async())`（順序厳守: stop→join→close、#081指摘#8・closeとworkerの競合回避）
4. `close_all`/`close_async` は削除対象から外す（使用する）

### 2b. ホットリロード配線（3バグ先修正）
1. **qdrantコールバックのasyncio.run問題**（#081指摘#3）: `on_qdrant_change`を専用スレッド+独自イベントループで実行（embedding/rerankerと同様のパターン）。イベントループ内からの`asyncio.run()`RuntimeError→サイレント失敗を解消
2. **`_reload_worker`のtry/finally**（#081指摘#6）: 反復中の例外でも必ずterminal status（"error"等）をset。RuntimeError（反復中のペルソナ生成）も捕捉
3. **コールバック登録の冪等ガード**（#081指摘#7）: RuntimeConfigManagerはシングルトンで`_callbacks`が永続。登録済みフラグで重複登録防止
4. 上記修正後、main.py（create_app後）で `register_model_reload_callbacks(RuntimeConfigManager())` を1行呼び出し

### 2c. event_bus定数化
- service.py:111,202,252 / session_event_recorder.py:30-33,80-90 の生文字列を `event_bus` 定数参照に置換（循環importなし・#081素通し判定済み）
- フロントエンド（activity.js等）の文字列はプロトコル値なので**触らない**

## テスト
- 新規: worker Event停止テスト（stop→joinがtimeout内に返る）、ホットリロード3修正の回帰テスト（status terminal保証・冪等登録・qdrantコールバックがループ外で動く）
- 既存: 全unitテスト pass / ruff 0 / mypy 新規エラー0 / カバレッジ≥60%

## 検証コマンド
```
.venv\Scripts\python.exe -m pytest tests -x -q
.venv\Scripts\python.exe -m ruff check nous scripts
.venv\Scripts\python.exe -m mypy nous
```

## リスクと注意
- 削除はvulture+#009裏取り+#081レビュー済みだが、削除後にimportエラーが出たら即修正（動的参照の見落とし）
- INDEPENDENT / serve_static / cli/__main__.py / _expand_segments / normalize_* / build_* / enrich_async / reload_model を誤って削らない
- uvicorn依存は既存（FastMCPが内部使用）のはず。requirementsに無ければ追加

---

# Phase 3: hebbian配線＋memoragフラグ修正（2026-09-05 追記、#081設計判断済み）

## スコープ外（明示的にやらない）
- decay()配線: スケジューラ設計が別途必要。メソッドはdataclassに残置（将来配線時の契約）
- MemoryContextSnapshot消費者の実装: 消費者ゼロが判明（build-sideのみのデッドエンド）。配線か削除かは次の判断に回す
- registryのtool.called二重発行解消: 既存挙動、activity表示への影響調査が別途必要

## 3a. hebbian配線（トラッカー方式——session_events経由は採用しない）

#081判断: session_events経由は二重tool.calledイベント・20件窓の浸食・summary文字列解析の脆弱性で死に経路。**AppContext上のインメモリ共アクセストラッカー**を採用（永続性を失うがhebbianは漸進的再構築なので損失ゼロ）。

1. **共アクセストラッカー**: AppContextにインメモリトラッカー（セッション内で読まれたmemory keyの順序リスト、上限は既存設計準拠）。memory_read/memory_createのMCPツール関数（_tools_memory.py、キーを手に持っている箇所）で記録
2. **Memory lookup**: `MemoryLinkService.__init__`に`memory_repo`を追加（service.py:79の構築箇所で渡す）。`_get_session_memories`はトラッカーのキー列を`memory_repo.get(key)`でMemoryオブジェクトに変換（失敗スキップ）して`list[Memory]`を返す。link_service.py:65のTODOと:93-95の型不一致（candidate.key/m1.emotion AttributeError未爆弾）を同時に解消
3. **EntityRepository拡張**（新規ファイルは作らない——link_repoの実体は既にSQLiteEntityRepository）:
   - `upsert_link(source_key, target_key, link_type, strength=0.1)`: 単一ステートメントで原子的に `INSERT ... ON CONFLICT(source_key, target_key, link_type) DO UPDATE SET weight = MIN(1.0, weight + :strength), co_activation_count = co_activation_count + 1, last_activated = :now`。読み取り→加算→書込の3ステップ禁止（競合原理的に排除）
   - 双方向は読み取り側で展開: `get_links_for_keys`は`WHERE source_key IN (?) OR target_key IN (?)`で1行取得し、順方向+逆方向の2つのMemoryLinkを生成（SAはoutgoingのみ参照: spreading_activation.py:46）
4. **get_links_for_keysのユニオン読替え**（フォールバックではなく統合）: entity共起エッジ（weight=0.5）をベースにmemory_linksの永続エッジを上書き統合。同一ペアは永続weight優先、永続のみのペアは新規追加（entity非共有ペアを繋ぐのがhebbianの唯一の価値）。Day-1挙動は現行と完全同一（memory_links空→共起のみ）。engine.py:416のSAブーストキャップ`min(act*0.2, 0.1)`は**いじらない**
5. **hebbian_update復元**: git履歴（abe0ffe2~1）から逐語復元（weight=min(1.0,weight+strength)/count++/last_activated更新）。テストも削除済みtest_memory_links.pyのhebbian部分から復元
6. **_create_hebbian_links**: トラッカー→Memory lookup→upsert_link呼び出しに変更。自己リンクskip・上限5件は既存設計準拠

## 3b. session_id付与（hebbianから独立したデータ品質修正）
- registry.py:96-104/110-119のtool.called発行に`"session_id": getattr(ctx, "session_id", None)`を追加
- MCPツール側の発行箇所（_tools_memory.py等）にも同様に
- 購読者はSessionEventRecorderのみ（recorder.py:43が`data.get("session_id", "unknown")`で既にキーを読む）→後方互換、「unknown」汚染が消えるだけ

## 3c. memoragフラグ不整合修正（drive-by）
- 役割: `settings.memorag.enabled`（settings.py:52、既定True）=グローバルinfraキルスイッチ / `ChatConfig.memorag_enabled`（session_config.py:100、既定False）=ペルソナ別機能ON/OFF
- 現状バグ: main.py:207-213がsettings(True)でworker生成するがstart()（worker.py:32）はデフォルトChatConfigのmemorag_enabled=Falseを判定→常にskip
- 修正: (1)`start()`の判定を`self._settings.memorag.enabled`のみに (2)`_rebuild_persona`内で`ChatConfigRepository(ctx.connection).get(persona)`をロードし、memorag_enabled=Falseのペルソナはskip。interval/top_kもペルソナ設定優先（worker.py:41-45,79の既存フォールバック構造を活用）
- 注意: スナップショットの消費者は現状ゼロ（build-sideのみ）。workerが動き始めても可視影響なし（LLMフリー、24h毎）

## テスト（最小6本）
1. upsert_link: 新規挿入→weight 0.6/count 1、再upsert→加算（0.7/count 2）、6回連続→cap 1.0
2. get_links_for_keysユニオン: memory_links空→共起のみ（現行回帰ガード）、永続リンクあり→永続weight優先・新規ペア追加・逆方向展開
3. link_service: トラッカー→Memory lookup→実DB（tmp）にリンク行作成、自己リンクskip・上限5件
4. hebbian_update単体: cap/count/last_activated（git履歴からテスト復元）
5. memorag: settings.memorag.enabled=False→スレッド起動なし、_rebuild_personaがmemorag_enabled=Falseペルソナをskip
6. session_id付与: registry発行イベント→recorderがsession_idを永続化

## 検証コマンド（Phase 1/2と同じ）
```
.venv\Scripts\python.exe -m pytest tests -x -q
.venv\Scripts\python.exe -m ruff check nous scripts
.venv\Scripts\python.exe -m mypy nous
```

---

# Phase 4: 残フォローアップ4件（2026-09-05 追記、#081設計判断済み）

実装順序: F4 → F3 → F2 → F1（F1はUI削除含むため最後・独立コミット推奨）

## F4. ChatConfig二重実装の解消（SQLite版削除・マイグレーション経路は残す）
- `chat_settings`テーブルはschema.pyに存在しない（CREATE TABLEゼロ）——SQLite版repoはレガシーDB専用の遺物。本番利用者はPhase 3でゼロになった
- (1) `_get_base_type`をモジュールレベル関数に移動（`ChatConfigFileRepository._migrate_from_sqlite`が参照中: chat_config.py:444）
- (2) `ChatConfigRepository`クラス削除（chat_config.py:215-402）＋`_TYPE_SQL`削除（:38、SQLite repo内でのみ使用）
- (3) `_migrate_from_sqlite`は**残す**——既存デプロイのmemory.sqlite→config.json一回限りアップグレード経路。生SQLで読むのでクラス削除と独立
- (4) schema.pyは触らない（テーブル定義なし確認済み、レガシーDBのテーブルは自然に残る）
- (5) tests: TestChatConfigRepository/TestChatConfigRepositoryResilience削除。**TestSqliteMigrationは移植**——レガシーテーブルのセットアップをrepoクラスから生SQL（CREATE TABLE+INSERT）に変え、マイグレーション経路のカバレッジ維持

## F3. tool.called二重発行の解消
- 不変条件: **「MCPツールは自分のイベントを自分で発行する（全パスで）。registryはMCP以外だけ発行する」**
- MCPツール側は絶対に止めない——直接MCP呼び出し（Claude Desktop等）の唯一の記録経路だから
- (1) registry.py:95/110の発行条件に`and not self.is_mcp_tool(tool_name)`を追加（2箇所）。builtin/search_toolsはregistry発行のまま
- (2) 自己発行ゼロの5個のMCPツール（memory_create・memory_update・memory_delete・invoke_skill・update_context）に成功・失敗パスの発行を追加（既存28箇所と同一パターン、session_id付き）
- (3) result_summaryのregistry側抽出は**やらない**——リッチなsummaryはツール関数が持つ知識
- activity.jsはレンダリングのみでペア前提なし→フロントエンド変更不要
- テスト: (a) registryがMCPツール名で発行しない（mock mcp_pool）(b) builtinでは発行する (c) **監査テスト**: 全13 MCPツール関数をmock ctxで成功・失敗パス両方呼び、`tool.called`発行≥1をパラメータ化で強制（不変条件の自動保証・ツール追加時の発行忘れ防止）

## F2. decay()配線（最小実装・floor 0.5の不変条件が命）
- **最重要不変条件: 永続weight ≥ 0.5**。union読替えは「永続weightが共起0.5を上書き」するため、floor 0.1で減衰すると減衰リンク(0.1)が共起0.5を上書きして**逆に劣化**する。減衰は[0.5, 1.0]区間内の差別化のみ
- (1) `EntityRepository.decay_stale_links(cutoff_iso, rate, floor=0.5)` — **単一UPDATE文**: `UPDATE memory_links SET weight = MAX(?, weight - ?) WHERE last_activated < ? AND weight > ?`（cutoffはPython側で計算して渡す。N+1禁止）
- (2) 配線: `DecayWorker._decay_cycle`末尾に1行（per-persona ctx、hourlyサイクルを流用——**別workerは作らない**）
- (3) パラメータ: idle閾値7日、rate 0.005/cycle（hourly）→1.0→0.5が約11日放置で到達。定数はメソッドデフォルト引数に置く（ハードコード禁止）
- (4) `MemoryLink.decay()`（dataclass、floor 0.1）は**削除**（テストも）——SQL方式を採るなら再びデッドになる
- テスト: decay_stale_links単体4本（新規リンク無影響/7日超で-rate/floor 0.5で停止/境界日時）+ workerが呼ぶことの1本

## F1. MemoryContextSnapshot機能の削除（カスケード全体・半端削除禁止）
#081判断: 消費者は一度も存在せず、context_loader.py:178-277が既に充実した文脈注入を持つため重複。本物のMemoRAGはLLM呼び出しを要する新設計であって「配線」ではない。`SearchEngine._memorag_config`は保存されるだけで一度も読まれない（engine.py:104/113）。
1. `nous/application/workers/context_snapshot_worker.py`削除＋main.py:204-213の生成ブロック（_workers登録も）
2. `nous/domain/search/context_snapshot.py`削除
3. `SearchEngine.__init__`の`memorag_config`引数と`self._memorag_config`（engine.py:104/113）＋use_cases.py:406-415の構築ブロック
4. `session_config.py:96-101`のmemorag_* 6フィールド——pydantic既定はextra='ignore'なので既存config.jsonの残存キーは読み飛ばされるだけで壊れない
5. WebUI: chat_sidebar.py（13箇所）・chat-settings.js（12箇所）・chat-core.js（1箇所）のmemoragセクション削除——**UI変更なので実確認必須**（agent-browser不在のためサーバー起動＋HTTPレベル確認で代替: ページレンダリング・memoragセクション不在・他セクション無傷）
6. settings.py:49-52のMemoragSettings削除（runtime_config/adminには露出なし確認済み）
7. テスト: test_context_snapshot_worker.py削除
8. 既存DBの`_global_context`ブロック（memory_blocks内）は**放置**（読まれないだけで無害、クリーンアップSQL不要）

## Phase 4検証コマンド
```
.venv\Scripts\python.exe -m pytest tests -x -q
.venv\Scripts\python.exe -m ruff check nous scripts
.venv\Scripts\python.exe -m ruff format --check nous scripts tests
.venv\Scripts\python.exe -m mypy nous
```
