# TODO: 残課題 2 件（アイテムツール圧縮 + OpenSandbox ペルソナ分離）

## ✅ 完了済み Phase (前回セッション)
- WebUI sandbox 残骸処理（Phase 0-3）→ 全 Phase 完了済み
- HANDOFF.md:69「残課題 2 件」に引き継ぎ済み

---

## Phase A: アイテムツール 7 → 3 圧縮

### T01: MCP ツール定義削除 [極小]
- [ ] `nous/api/mcp/_tools_item.py` から `_tool_item_remove` (L51-77), `_tool_item_unequip` (L109-136), `_tool_item_update` (L139-182), `_tool_item_history` (L228-266) を削除
- [ ] ファイル末尾を `_tool_item_search` (L185-225) のみ残す
- **依存**: なし
- **担当**: @fixer

### T02: 登録・スキーマ削除 [極小]
- [ ] `nous/api/mcp/tools.py` の import (L33-41) から 4 件削除
- [ ] dispatch dict (L67-73) から 4 件削除
- [ ] `@_tool` 関数 (L311-359) から 4 件削除
- [ ] `nous/application/chat/tools/definitions.py` の `CORE_ALWAYS_TOOLS` (L24-30) から 4 件削除
- [ ] `MEMORY_TOOLS` dict (L183-273) から 4 つの `ToolDefinition` 削除
- [ ] `_NOUS_TOOL_NAMES` frozenset (L412-418) から 4 件削除
- **依存**: T01
- **担当**: @fixer

### T03: dead code 削除 [極小]
- [ ] `nous/domain/equipment/service.py` の `get_history()` (L212-214) 削除
- [ ] `nous/domain/equipment/repository.py` の Protocol `get_history` (L42) 削除
- **依存**: T01
- **担当**: @fixer

### T04: テスト削除 [小]
- [ ] `tests/unit/test_mcp_items.py` の 4 テストケース削除 (L87, 113, 126, 156)
- [ ] `tests/unit/test_mcp_items.py` の fixture 整理（4 ツール分のモック削除）
- [ ] `tests/unit/test_sqlite_repos.py` の `test_get_history` (L314) 削除
- **依存**: T01-T03
- **担当**: @fixer
- **テストスコープ**: 自身の変更ファイルのみ。`test_equipment_service.py` の `TestUnequip` はサービスメソッドが残るため維持。

### T05: ドキュメント更新 [極小]
- [ ] `docs/llm_usage_guide.md` L22 ツール一覧から 4 件削除、L743-744 使用例更新
- [ ] `CLAUDE.md` L76-81 ツール一覧を 3 件に更新
- [ ] `README.md` L115 ツール一覧を 3 件に更新
- [ ] `.spec/TEST_PLAN.md` IT-09, IT-10, IT-11, IT-12, IT-13 の再分類
- [ ] `.spec/TEST_RESULTS.md` L96-100 テスト結果行を削除
- **依存**: T01-T04
- **担当**: orchestrator（ドキュメントは orchestrator 責務）

---

## Phase A: アイテムツール 7 → 3 圧縮

### ✅ T01: MCP ツール定義削除
- [x] `nous/api/mcp/_tools_item.py` から `_tool_item_remove`, `_tool_item_unequip`, `_tool_item_update`, `_tool_item_history` を削除
- [x] ファイル末尾を `_tool_item_search` のみ残す
- **コミット**: `766d46d`

### ✅ T02: 登録・スキーマ削除
- [x] `nous/api/mcp/tools.py` の import / dispatch / `@_tool` から 4 件削除
- [x] `nous/application/chat/tools/definitions.py` の `CORE_ALWAYS_TOOLS` / `MEMORY_TOOLS` / `_NOUS_TOOL_NAMES` から 4 件削除

### ✅ T03: dead code 削除
- [x] `nous/domain/equipment/service.py` の `get_history()` 削除
- [x] `nous/domain/equipment/repository.py` の Protocol `get_history` 削除

### ✅ T04: テスト削除
- [x] `tests/unit/test_mcp_items.py` の 4 テストケース削除 + fixture 整理
- [x] `tests/unit/test_sqlite_repos.py` の `test_get_history` 削除
- **結果**: pytest 53 passed (削除前 58 → 削除後 53、差分 = 削除テスト数 5)

### 🔄 T05: ドキュメント更新 (orchestrator 責務)
- [ ] `docs/llm_usage_guide.md` L22 ツール一覧から 4 件削除、L743-744 使用例更新
- [ ] `CLAUDE.md` L76-81 ツール一覧を 3 件に更新
- [ ] `README.md` L115 ツール一覧を 3 件に更新
- [ ] `.spec/TEST_PLAN.md` IT-09, IT-10, IT-11, IT-12, IT-13 の再分類
- [ ] `.spec/TEST_RESULTS.md` L96-100 テスト結果行を削除

---

## Phase B: OpenSandbox MCP ペルソナ分離（案 B'）

### ✅ T06: 設計レビュー
- [x] `@oracle` に docker-compose 動的生成方式の最終設計レビュー依頼
- [x] 案 B → 案 B' に変更（init container 方式を棄却、静的 YAML テンプレ採用）
- [x] リスク評価: port 上限、後方互換、persona 動的追加（事前宣言方式で解決）
- **結果**: 案 B' 採用、コスト 3-5h、シンプルイズベスト

### ✅ T07: docker-compose 静的 YAML 化 [小]
- [x] `docker-compose.yml` に `x-opensandbox-mcp` アンカー追加
- [x] `NOUS_PERSONAS` と同数の `opensandbox-mcp-{persona}` サービス定義を手動追加 (herta, alice, bob)
- [x] port マッピングは `8001:8000`, `8002:8000`, `8003:8000` のデバッグ用のみ
- **コミット**: `5cd3cb0`

### ✅ T08: chat_config.py factory 化 [小]
- [x] `nous/domain/chat_config.py` の `DEFAULT_MCP_SERVERS` を `_get_default_mcp_servers(persona)` factory 関数に置換
- [x] `os.environ.get("NOUS_OPENDBOX_MCP_URL")` で完全 override 対応
- [x] 既存 DB の `mcp_servers` 設定は上書きしない（後方互換）
- **コミット**: `5cd3cb0`

### ✅ T09: persona 削除時の sandbox クリーンアップ [中]
- [x] `nous/api/http/routers/persona.py` の `delete_persona` に `_cleanup_opensandbox_sandboxes` best-effort クリーンアップ追加
- [x] `httpx.AsyncClient` で JSON-RPC `sandbox_list` → 各 `sandbox_kill`
- [x] 失敗しても `shutil.rmtree` フローは継続
- [x] 単体テスト追加 (9 tests)
- **コミット**: `5cd3cb0`

### ✅ T10: 環境変数・ドキュメント [極小]
- [x] `.env.example` に `NOUS_PERSONAS`, `NOUS_OPENDBOX_MCP_URL` 追記
- [x] `docs/llm_usage_guide.md` にペルソナ分離アーキテクチャ説明追加
- [x] `CLAUDE.md` アーキテクチャ図更新
- **コミット**: `5cd3cb0`

---

## Phase C: 検証・ドキュメント最終化

### 🔄 T11: Phase A 検証 ✅ 完了済み
- [x] `ruff check .` → 0 errors
- [x] `ruff format --check .` → clean
- [x] `pytest tests/unit/test_mcp_items.py tests/unit/test_equipment_service.py tests/unit/test_sqlite_repos.py` → 53 passed
- [x] MCP ツール一覧確認（残り 3 ツール = item_add, item_equip, item_search）

### 🔄 T12: Phase B 検証
- [ ] `docker compose up -d` → 全サービス healthy
- [ ] 動作確認手順 6 ステップすべて pass
- [ ] `docker compose ps` で `opensandbox-mcp-{persona}` ごとに起動確認
- [ ] 別 persona の sandbox_id で cross-access 不可を確認

### 🔄 T13: 全テストスイート実行（orchestrator のみ）
- [ ] `pytest tests/ --ignore=tests/benchmark --ignore=tests/integration/test_dashboard_e2e.py -q` → 全パス
- [ ] `pytest tests/integration/test_dashboard_e2e.py` → 全パス

### 🔄 T14: コミット + push + CI
- [ ] Phase A のコミット `766d46d` push
- [ ] Phase B のコミット（feat/opensandbox-persona-isolation）
- [ ] `git push` → GitHub Actions 通過確認
- [ ] 失敗時はデバッグ・ワークフロー修正して pass まで

### 🔄 T15: HANDOFF.md 更新
- [ ] 完了内容、残課題、学びを `.agent/handoff/HANDOFF.md` に記述
- [ ] `.agent/memory/MEMORY.md` 200 行以内維持

---

## 実行順序

```
Group 0: Phase A 並列着手 ✅ 完了
  - T01, T02, T03, T04 完了 (コミット 766d46d)
  - T05: orchestrator のドキュメント更新待ち

Group 1: Phase B 設計 ✅ 完了
  - T06 (oracle レビュー → 案 B' 採用)

Group 2: Phase B 実装 ← 今ここ
  - T07, T08, T09 を順次（依存関係あり、@fixer）

Group 3: Phase C 検証
  - T11 ✅ 完了、T12, T13, T14, T15
```

## 検証ゲート（各 Phase 完了後）

1. Phase A 完了 → `ruff check .` + `pytest tests/unit/test_mcp_items.py tests/unit/test_equipment_service.py tests/unit/test_sqlite_repos.py` 全パス
2. Phase B 完了 → `docker compose up -d` 全 healthy + 動作確認 6 ステップ pass
3. Phase C 完了 → 全テストスイート green + CI green + HANDOFF 更新
