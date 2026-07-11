# HANDOFF — 2026-07-11 11:15

## セッション概要
HANDOFF.md:69 の残課題 2 件（アイテムツール 7→3 圧縮、OpenSandbox MCP ペルソナ分離）を完全解消。
3 コミット / 全テスト 1615 passed / ruff clean / YAML 構文 OK。

## 作業ブランチ
```
main
```

## コミット履歴
```
f43d139 docs: アイテム 7→3 ツール圧縮のドキュメント反映 (Phase A T05)
5cd3cb0 feat: OpenSandbox MCP ペルソナ分離（per-persona instance 化）
766d46d feat: アイテムツール 7→3 圧縮（YAGNI 解消）
```

## 完了したこと

### Phase A: アイテムツール 7→3 圧縮（コミット 766d46d, 7 ファイル / -322 行）

YAGNI 違反だった 4 ツールを削除。`memory_llm.inventory_update` 機構が代替を担う。

| 削除 | 残す |
|------|------|
| `item_remove` | `item_add` |
| `item_unequip` | `item_equip` |
| `item_update` | `item_search` |
| `item_history` | |

- `equipment_service.get_history()` / `repository.get_history()` も dead code として同時削除
- REST API / フロントエンドは影響なし
- テスト: 53 passed (削除前 58 → 削除後 53)

### Phase B: OpenSandbox MCP ペルソナ分離（コミット 5cd3cb0, 7 ファイル / +290/-38 行）

**採用方式: 案 B'（静的 YAML + URL factory）**。Oracle レビューで SPEC の init container 方式を棄却し、シンプルイズベストに舵を切った。

アーキテクチャ:
```
単一 opensandbox (port 8090)
  ├── opensandbox-mcp-herta (port 8001, 独立 ServerState)
  ├── opensandbox-mcp-alice (port 8002, 独立 ServerState)
  └── opensandbox-mcp-bob   (port 8003, 独立 ServerState)
```

| タスク | 内容 |
|--------|------|
| T07 | `docker-compose.yml` を `x-opensandbox-mcp` アンカー + 3 サービス (herta/alice/bob) に書き換え。port 8001-8003 |
| T08 | `chat_config.py` の `DEFAULT_MCP_SERVERS` を空に、`_get_default_mcp_servers(persona)` factory 追加。`NOUS_OPENDBOX_MCP_URL` で完全 override 可能 |
| T09 | `delete_persona` に best-effort な OpenSandbox sandbox クリーンアップ追加（`_cleanup_opensandbox_sandboxes` / `_parse_mcp_response`）。9 テスト新規 |
| T10 | `.env.example` に `NOUS_PERSONAS` / `NOUS_OPENDBOX_MCP_URL` 追記、`docs/llm_usage_guide.md` ペルソナ分離セクション追加、`CLAUDE.md` 外部MCPテーブル更新 |

### Phase A T05: ドキュメント反映（コミット f43d139, 5 ファイル / -12 行）

7→3 圧縮に合わせて以下を更新:
- `docs/llm_usage_guide.md` L22: 7 ツール名 → 3 ツール名
- `CLAUDE.md` L75-81: 7 行 → 3 行
- `README.md` L115: `(7ツール)` → `(3ツール)`
- `.spec/TEST_PLAN.md` IT-09〜13: 5 行削除（IT-12 のみ `~~item_remove~~` として履歴残し）
- `.spec/TEST_RESULTS.md` L96-100: 同様に 5 行削除

## 検証状況

```
ruff check: 0 errors
ruff format: clean
pytest tests/ --ignore=tests/benchmark --ignore=tests/integration/test_dashboard_e2e.py: 1615 passed, 7 skipped
YAML syntax (docker-compose.yml): OK
```

## 環境変数（運用者向け）

```bash
# 必須: ペルソナ一覧（カンマ区切り）
NOUS_PERSONAS=herta,alice,bob

# オプション: URL テンプレート完全 override
# デフォルト: f"http://opensandbox-mcp-{persona}:8000/mcp"
# NOUS_OPENDBOX_MCP_URL=http://custom-host:9999/mcp
```

## 既知事項 / 次セッション候補

- **T12 実機確認**: `docker compose up -d` で全サービス起動 + 動作テスト（未実施・環境依存）
- **T14 push + CI**: `f43d139` まで main ブランチに push、GitHub Actions パス確認
- **persona 追加手順**: 新しい persona を増やす場合、(1) `docker-compose.yml` に `opensandbox-mcp-{persona}` サービス追加、(2) `NOUS_PERSONAS` 環境変数に追記、(3) `POST /api/personas/{persona}` で作成、の 3 ステップが必要
- **persona 数の上限**: 現状 herta/alice/bob の 3 つまで静的定義。増やす場合は docker-compose.yml の手動編集が必要
- `DEFAULT_MCP_SERVERS` 定数は空にしたが import 後方互換のため削除せず残置（grep で確認した範囲では import なし）

## 関連ドキュメント

- `.spec/PLAN.md` — 残課題 2 件の背景・目的
- `.spec/SPEC.md` — 詳細仕様（案 B ベース、案 B' 採用は本 HANDOFF に記録）
- `.spec/TODO.md` — Phase A/B/C のタスク分解
