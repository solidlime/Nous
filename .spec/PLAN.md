# PLAN: 残課題 2 件（2026-07-11）

## 背景

`feat/browser-sandbox-mcp` マージ後、`.agent/handoff/HANDOFF.md:69` で「残課題」として記録された 2 件。
`MEMORY.md:95` でも「アイテム系 7 ツールが YAGNI 違反」と評価済み。実機構成は TODO.md Phase 3 の
「docker compose up による実機確認」と一体。

両者とも緊急性低だが、Nous の MCP 統合ストーリーを完全なものにするには避けて通れない。

---

## 残課題 ① アイテムツール 7 → 3 圧縮

### 問題

`item_add / item_remove / item_equip / item_unequip / item_update / item_search / item_history` の
7 ツールは M CP 経由で LLM に公開されているが、そのうち 4 つは LLM にとって不要。

- `item_remove` / `item_unequip` / `item_update` は **memory_llm** の `inventory_update` 機構が
  LLM 出力の JSON から直接 `equipment_service` を操作するため、MCP ツールとして公開する意味がない
- `item_history` は他のどこからも呼ばれていない（REST API / memory_llm ともに経由せず）

### 残すツール

- `item_add` — LLM が新規アイテム登録に使う
- `item_equip` — LLM が装備変更に使う
- `item_search` — LLM がインベントリ確認に使う

### 副次効果: dead code 削除

`equipment_service.get_history()` は `item_history` を削除すると呼び出し元がゼロになる。
リポジトリ層の `get_history()` と `test_sqlite_repos.py::test_get_history` も同時に削除する。

### スコープ

- MCP ツール定義: `_tools_item.py` の 4 関数削除
- 登録: `tools.py` の import / dispatch / `@_tool` デコレータから 4 件削除
- チャットツールスキーマ: `definitions.py` の `CORE_ALWAYS_TOOLS` / `MEMORY_TOOLS` / `_NOUS_TOOL_NAMES`
- テスト: `tests/unit/test_mcp_items.py` の 4 テストケース
- dead code: `equipment_service.get_history()` + `repository.get_history()` + 関連テスト
- ドキュメント: `docs/llm_usage_guide.md` / `CLAUDE.md` / `README.md` / `.spec/TEST_PLAN.md` / `.spec/TEST_RESULTS.md`

---

## 残課題 ② OpenSandbox MCP ペルソナ分離の実機構成

### 問題

`docker-compose.yml` の `opensandbox-mcp` は単一コンテナで、`ServerState`（`sandbox_id → Sandbox` の
インメモリマップ）を全ペルソナで共有している。`sandbox_id` さえ分かれば別ペルソナのサンドボックスに
侵入可能（セキュリティホール）。さらに「ペルソナ A の実行結果がペルソナ B に見える」状態は UX 上の事故。

### 解決方針（案 B 採用）

**per-persona `opensandbox-mcp` インスタンス化**。

- 単一の `opensandbox` サーバーは維持（Docker ソケット管理を一元化）
- 各 persona ごとに `opensandbox-mcp` コンテナを立ち上げ、port を分ける
- 各 `opensandbox-mcp` インスタンスは独立した `ServerState` を持つ
- 既存の `ChatConfig.mcp_servers`（per-persona SQLite 保存）を活用し、各 persona が自分の MCP サーバーを指す

### 効果

- ✅ ServerState のメモリレベル分離（sandbox_id のクロスリーク不可能）
- ✅ 片方 MCP のクラッシュが他 persona に波及しない
- ✅ persona ごとに異なる `opensandbox` イメージ/リソース制限の余地
- ✅ 既存の per-persona DB / per-persona `mcp_servers` 設定に自然適合

### スコープ

- `docker-compose.yml`: 動的 persona-aware サービス定義（init スクリプト方式）
- `nous/domain/chat_config.py` `DEFAULT_MCP_SERVERS`: 環境変数 `NOUS_PERSONAS` から動的生成
- persona 作成フック: 新規 persona 作成時に `mcp_servers` を persona 用 URL に自動設定
- persona 削除フック: 該当 MCP コンテナ停止 + ボリューム削除
- 動作確認: 各 persona からの `opensandbox__execute_code` が独立した filesystem を持つこと

---

## 順序

```
Phase A: アイテムツール圧縮（並列着手可）
  ① fixer A: _tools_item.py 4 関数削除
  ② fixer B: tools.py / definitions.py から 4 件削除
  ③ fixer A: dead code (get_history) 削除
  ④ fixer A: テスト 4 件削除 + 関連 2 件
  ⑤ orchestrator: ドキュメント 5 ファイル更新

Phase B: OpenSandbox ペルソナ分離（順次）
  ⑥ oracle: docker-compose 動的生成の最終設計レビュー
  ⑦ fixer C: docker-compose.yml / scripts/ 拡張
  ⑧ fixer C: chat_config.py の DEFAULT_MCP_SERVERS 動的化
  ⑨ fixer C: persona create/delete フック
  ⑩ orchestrator: docker compose up 実機確認

Phase C: 検証・ドキュメント
  ⑪ 全テストスイート実行（orchestrator のみ）
  ⑫ ドキュメント最終更新（CLAUDE.md / docs/llm_usage_guide.md / README.md）
  ⑬ コミット + push + CI 確認
  ⑭ HANDOFF.md 更新
```

## 質問

- Phase A は破壊的変更（API から 4 ツール消失）。LLM プロンプトやシステムメッセージで「`item_remove` 使えます」的な記述があれば影響あるか → 確認したい
- Phase B の per-persona MCP コンテナ数の上限は？ persona 数 10+ を想定するか、3-5 程度か
