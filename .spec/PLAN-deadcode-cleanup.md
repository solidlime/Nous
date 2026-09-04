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
