# SPEC: 残課題 2 件（アイテムツール圧縮 + OpenSandbox ペルソナ分離）

## ① アイテムツール 7 → 3 圧縮（YAGNI 解消）

### 設計原則

- **MCP ツールは LLM が必要とするものだけ残す**
- 内部処理（inventory_update / REST API / prepare.py）は無関係、影響ゼロ
- dead code は同時削除してリポジトリを綺麗に保つ

### 残すツール（3個）

| ツール | 役割 | LLM 必要性 |
|--------|------|----------|
| `item_add` | 新規アイテム登録 | LLM が「これは新しい」と言いたい時に必要 |
| `item_equip` | 装備変更（スロット一括） | LLM が「着替える」「装備する」を表現する時に必要 |
| `item_search` | インベントリ照会 | LLM が「何持ってる？」を確認するのに必要 |

### 削除するツール（4個）と根拠

| ツール | 削除根拠 |
|--------|---------|
| `item_remove` | `memory_llm.inventory_update` が JSON から直接 `equipment_service.remove_item()` を呼ぶ。LLM が MCP ツールとして個別に呼ぶ必要がない。 |
| `item_unequip` | 同上。`memory_llm` から直接 `unequip()` を呼ぶ経路あり。 |
| `item_update` | 同上。`memory_llm` から直接 `update_item()` を呼ぶ経路あり。 |
| `item_history` | **どの経路からも呼ばれていない**（REST API / memory_llm / フロントエンド全て）。完全デッドコード。 |

### 変更ファイル一覧

| # | ファイル | 変更内容 |
|---|---------|---------|
| 1 | `nous/api/mcp/_tools_item.py` | `_tool_item_remove` (L51-77), `_tool_item_unequip` (L109-136), `_tool_item_update` (L139-182), `_tool_item_history` (L228-266) の 4 関数を削除。ファイル末尾は `_tool_item_search` (L185-225) のみ残す |
| 2 | `nous/api/mcp/tools.py` | Import リスト (L33-41) から 4 つ削除、Dispatch dict (L67-73) から 4 件削除、`@_tool` 関数 (L311-359) から 4 件削除 |
| 3 | `nous/application/chat/tools/definitions.py` | `CORE_ALWAYS_TOOLS` (L24-30) から 4 件削除、`MEMORY_TOOLS` dict (L183-273) から 4 つの `ToolDefinition` 削除、`_NOUS_TOOL_NAMES` frozenset (L412-418) から 4 件削除 |
| 4 | `nous/domain/equipment/service.py` | `get_history()` メソッド (L212-214) 削除 |
| 5 | `nous/domain/equipment/repository.py` | Protocol から `get_history` (L42) 削除 |
| 6 | `tests/unit/test_mcp_items.py` | `test_item_remove` (L87), `test_item_unequip` (L113), `test_item_update` (L126), `test_item_history` (L156) の 4 テストケース削除 + 関連 fixture 整理 |
| 7 | `tests/unit/test_sqlite_repos.py` | `test_get_history` (L314) 削除 |
| 8 | `docs/llm_usage_guide.md` | L22 ツール一覧から 4 件削除、L743-744 使用例更新 |
| 9 | `CLAUDE.md` | L76-81 ツール一覧を 3 件に更新 |
| 10 | `README.md` | L115 ツール一覧を 3 件に更新 |
| 11 | `.spec/TEST_PLAN.md` | IT-09, IT-10, IT-11, IT-12, IT-13 の再分類または削除 |
| 12 | `.spec/TEST_RESULTS.md` | L96-100 テスト結果行を削除 |

### 影響ゼロが確認できているもの

- `nous/api/http/routers/item.py` — REST API は `equipment_service` を直接呼ぶ、MCP ツール経由ではない
- `nous/application/chat/memory_llm.py` — 同上
- フロントエンド（`activity.js`, `sections/activity.py`）— `tool.called` イベントに依存しない汎用ハンドラ
- `EquipmentHistory` エンティティ — 装備変更の履歴書き込みには継続使用

---

## ② OpenSandbox MCP ペルソナ分離の実機構成

### 設計原則

- **OpenSandbox 公式の per-sandbox filesystem 分離を最大活用**（既に成立）
- **sandbox_id の可視性スコープを persona ごとに制限**（課題）
- **Nous 側だけで完結**（OpenSandbox のフォーク・改造はしない）
- **既存 per-persona 設定機構を再利用**（`ChatConfig.mcp_servers`）
- **シンプルイズベスト**（init container 動的生成は不採用 — 静的 YAML で十分）

### アーキテクチャ（案 B' 採用: 静的 YAML テンプレ + URL factory）

**Oracle レビュー（2026-07-11）により SPEC の init container 方式を棄却、案 B' に変更**:

```
┌─────────────────┐
│   opensandbox   │ ← 単一サーバー（port 8090、全 sandbox を管理）
│   (FastAPI)     │
└────────┬────────┘
         │  HTTP
   ┌─────┴─────┬─────┬─────┐
   ▼           ▼     ▼     ▼
┌────────┐ ┌────────┐ ┌────────┐
│mcp-herta│ │mcp-alice│ │mcp-bob │  ← per-persona インスタンス
│:8001   │ │:8002   │ │:8003   │     独立した ServerState
└────────┘ └────────┘ └────────┘
   ▲           ▲     ▲
   │           │     │
 ChatConfig[persona]  ChatConfig[persona]  ChatConfig[persona]
   (.sqlite)         (.sqlite)           (.sqlite)
   mcp_servers:      mcp_servers:        mcp_servers:
   opensandbox-mcp-herta:8000   ...alice:8000   ...bob:8000
```

各 `opensandbox-mcp-{persona}` は同一の `opensandbox` サーバーを指すが、別プロセス・別 `ServerState` を持つ。
コンテナ間通信は service name（`opensandbox-mcp-{persona}:8000`）で名前解決、port マッピングはデバッグ用ホストポートのみ。

### 棄却理由（init container 方式）

1. **`docker-compose.override.yml` 動的生成の罠**: 起動時ワンショットしか評価されない、`POST /api/personas` での動的追加が反映されない
2. **Nous コンテナに docker socket マウントが必要**: セキュリティ懸念（現状 Nous はマウントしていない）
3. **冪等性・誤削除・手動編集との競合**: gitignore 対象ファイルへの自動書き込みは事故りやすい
4. **複雑度に見合わない**: 静的 YAML で全要件が満たせる

### 変更ファイル一覧

| # | ファイル | 変更内容 |
|---|---------|---------|
| 1 | `docker-compose.yml` | `x-opensandbox-mcp` YAML アンカー追加、各 persona サービス `opensandbox-mcp-{persona}` 定義。port マッピングは `8001:8000`, `8002:8000`, ... のデバッグ用。コンテナ間通信は service name。 |
| 2 | `nous/domain/chat_config.py` | `DEFAULT_MCP_SERVERS` (L39-52) を `_get_default_mcp_servers(persona)` factory 関数に置換。`os.environ` から `NOUS_PERSONAS` を読んで persona → URL マッピングを生成。`NOUS_OPENDBOX_MCP_URL` 環境変数で完全 override 可能。 |
| 3 | `nous/infrastructure/sqlite/repositories/chat_config_repository.py` (要確認パス) | `get_or_create()` で `mcp_servers` 未設定時に `_get_default_mcp_servers(persona)` を呼ぶ。既存設定は上書きしない（後方互換）。 |
| 4 | `nous/api/http/routers/persona.py` | persona 削除時に `httpx` で `opensandbox-mcp-{persona}:8000/mcp` 経由 `sandbox_list` → 全 `sandbox_delete` の best-effort クリーンアップ追加。失敗しても削除フローは継続。 |
| 5 | `.env.example` | `NOUS_PERSONAS` + `NOUS_OPENDBOX_MCP_URL` の説明追記 |
| 6 | `docs/llm_usage_guide.md` | ペルソナ分離の説明セクション追加 |
| 7 | `CLAUDE.md` | アーキテクチャ図更新 |

### 環境変数

```bash
# 必須: ペルソナ一覧（カンマ区切り）
NOUS_PERSONAS=herta,alice,bob

# オプション: URL テンプレートを完全 override（advanced）
# デフォルト: f"http://opensandbox-mcp-{persona}:8000/mcp"
NOUS_OPENDBOX_MCP_URL=http://custom-host:9999/mcp
```

### chat_config.py 修正内容

```python
import os

def _get_default_mcp_servers(persona: str) -> list[dict]:
    """Generate per-persona MCP server configs.
    
    Reads NOUS_PERSONAS and constructs per-persona opensandbox URL.
    NOUS_OPENDBOX_MCP_URL overrides the URL template completely.
    """
    servers: list[dict] = [
        {
            "name": "playwright",
            "transport": "http",
            "url": "http://playwright:8931/sse",
            "enabled": True,
        },
    ]
    
    sandbox_url = os.environ.get("NOUS_OPENDBOX_MCP_URL")
    if not sandbox_url:
        sandbox_url = f"http://opensandbox-mcp-{persona}:8000/mcp"
    
    servers.append({
        "name": "opensandbox",
        "transport": "http",
        "url": sandbox_url,
        "enabled": True,
    })
    return servers

# 後方互換のため定数は残すが内容は空（各 persona 個別生成）
DEFAULT_MCP_SERVERS: list[dict] = []
```

### docker-compose.yml 修正内容

```yaml
x-opensandbox-mcp: &opensandbox-mcp
  image: python:3.11-slim
  command: >
    sh -c "pip install --no-cache-dir opensandbox-mcp &&
           opensandbox-mcp --transport streamable-http --domain opensandbox:8090 --protocol http"
  environment:
    TZ: Asia/Tokyo
  restart: unless-stopped
  depends_on:
    opensandbox:
      condition: service_healthy

services:
  opensandbox-mcp-herta:
    <<: *opensandbox-mcp
    container_name: opensandbox-mcp-herta
    ports: ["8001:8000"]  # デバッグ用
    
  opensandbox-mcp-alice:
    <<: *opensandbox-mcp
    container_name: opensandbox-mcp-alice
    ports: ["8002:8000"]
    
  opensandbox-mcp-bob:
    <<: *opensandbox-mcp
    container_name: opensandbox-mcp-bob
    ports: ["8003:8000"]
  # NOUS_PERSONAS と同数を手動追加（スクリプト生成なし）
```

### 動作確認手順（Phase B 完了後）

1. `NOUS_PERSONAS=herta,alice,bob` を `.env` に設定
2. `docker compose up -d` → 全サービス healthy
3. `persona=herta` の `mcp_servers` を DB で確認 → `http://opensandbox-mcp-herta:8000/mcp` が保存されていること
4. `persona=herta` で `opensandbox__execute_code(code="echo 'herta-secret' > /tmp/secret")` 実行
5. `persona=alice` で `/tmp/secret` が存在しないことを確認（別 sandbox / 別 filesystem）
6. `persona=herta` の `sandbox_list` が herta の sandbox のみ返すことを確認
7. 別 persona の `sandbox_id` で `sandbox_connect` を試行 → 別 MCP インスタンスの `ServerState` には存在しないので失敗
8. persona 削除時、`sandbox_*` もクリーンアップされることを確認

### ロールバック方法

- `docker-compose.yml` の `x-opensandbox-mcp` アンカー + 各サービス定義を削除、旧 `opensandbox-mcp` 単一サービスに戻す
- `chat_config.py` の `_get_default_mcp_servers()` を旧 `DEFAULT_MCP_SERVERS` ハードコードに戻す
- 既存 persona の DB 内 `mcp_servers` は `http://opensandbox-mcp:8000/mcp` のままなので、`get_or_create` は上書きしないため影響なし

---

## VERIFY: 検証

### ① アイテムツール圧縮

- `ruff check .` → 0 errors
- `python3 -m pytest tests/unit/test_mcp_items.py tests/unit/test_equipment_service.py tests/unit/test_sqlite_repos.py -v` → 全パス
- `python3 -m pytest tests/ --ignore=tests/benchmark --ignore=tests/integration/test_dashboard_e2e.py -q` → 全パス（orchestrator のみ）
- MCP ツール一覧が 3 ツールになっていることを `http://localhost:26262/api/mcp/tools` で確認

### ② OpenSandbox ペルソナ分離

- `docker compose up -d` → 全サービス healthy
- 上記「動作確認手順」6 ステップ
- `docker compose ps` で `opensandbox-mcp-{persona}` が各 persona ごとに起動していることを確認
- `http://localhost:8001/mcp` (herta) と `http://localhost:8002/mcp` (alice) が別プロセスであることを PID で確認
