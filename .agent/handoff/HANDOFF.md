# HANDOFF — 2026-07-11 19:30

## セッション概要

本セッションは「残課題 2 件（アイテムツール圧縮 + OpenSandbox ペルソナ分離）」の完了を起点に、
追加で「チャット UI バグ 3 件」「MCP ツール動作検証」「ローカル docker compose 検証」「設定振り分け P1-P5 実装」を実施。
**しかしユーザーから新たな要件（動的プロビジョニング + ハードコード廃止 + 本番環境起動失敗）が提示され、別セッションでの作業を決定**。

## 完了したコミット一覧（main ブランチ）

```
e00b27e fix(chat): builtin.py に import os 追加 (search fallback の修正漏れ)
2c0028d feat(config): irodori/portrait/opensandbox を ChatConfig 化 (P1+P2+P5 振り分け修正)
523746d fix(compose): playwright MCP サービスの Restarting loop 解消
8010925 fix(search) + chore(dev): SearXNG URL 環境変数統一 + dev compose + opensandbox/playwright 起動修正
f1f9ddb feat(chat): メッセージ直接編集API追加（undoスタック保護+UX向上）
025a3a1 fix(chat): ツール使用表示のタイミングを該当 assistant メッセージ直後に修正
b3ce399 fix(chat): 2-3回目以降のメッセージ送信不能を修正（DOMContentLoaded依存解消）
7366486 docs(spec): 残課題 2 件の SPEC/PLAN/TODO + MEMORY 反映
0643c8d docs(agent): HANDOFF 更新
f43d139 docs: アイテム 7→3 ツール圧縮のドキュメント反映
5cd3cb0 feat: OpenSandbox MCP ペルソナ分離（per-persona instance 化）
766d46d feat: アイテムツール 7→3 圧縮（YAGNI 解消）
```

## 検証状況

```
pytest tests/ --ignore=tests/benchmark --ignore=tests/integration/test_dashboard_e2e.py: 1646 passed / 7 skipped
ruff check: 0 errors
ruff format: clean
docker compose (dev): 全サービス Healthy
```

## 🎯 次のセッションで着手すべきタスク（優先度順）

### Priority A: 本番環境 docker-compose 起動失敗の修正【緊急】

ユーザーから「本番環境で docker-compose.yml で立ち上がらない」と報告。exp-3 で原因特定済み。

#### A-1: Volume 書き込み権限修正【HIGHEST】

**問題**: `docker-compose.yml:148` で `${DATA_ROOT}/app:/opt/nous/data` を bind mount しているが、
ホスト側の owner（root:root）がコンテナ内 nous ユーザーより優先され、`ensure_directories()` が PermissionError で全滅。

**修正方針**:
- オプション A: docker-compose.yml に `:Z` 追加（SELinux 対応 + owner remap）
- オプション B: 起動時に init container で `chown nous:nous /opt/nous/data` してから nous を起動
- オプション C: Dockerfile の `USER nous` 設定の見直し（root 起動→chown→drop privileges）

**修正対象**: `docker-compose.yml`, `Dockerfile`

#### A-2: opensandbox healthcheck 修正【HIGH】

**問題**: `docker-compose.yml:112` の healthcheck で `python` を使うが、
`opensandbox/server:latest` は Rust 製で Python を含まない。

**修正前**:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')"]
```

**修正後**:
```yaml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8090/health"]
  interval: 15s
  timeout: 5s
  retries: 3
```

**確認**: `wget` が opensandbox イメージに含まれるかは `docker run --rm opensandbox/server:latest wget --version` で確認。
含まれていなければ `wget` インストールを Dockerfile に追加するか、`/health` ファイルの作成を busybox ベースイメージで代替。

#### A-3: opensandbox-mcp の pip install 高速化【MEDIUM】

**問題**: `docker-compose.yml:6-7` で `pip install --no-cache-dir opensandbox-mcp` を毎回実行。
起動に 30-60秒追加、PyPI 障害で失敗リスク。

**修正方針**:
- オプション A: 専用 Dockerfile を作成（`Dockerfile.sandbox-mcp`）してイメージビルド化
- オプション B: pre-built イメージ（ghcr.io/solidlime/opensandbox-mcp:latest）を作成・利用
- オプション C: pip キャッシュボリューム使用（`--mount type=volume,source=pip-cache,target=/root/.cache/pip`）

### Priority B: 動的プロビジョニング実装（案 A: SandboxOrchestrator）

ユーザー要求:
- opensandbox の手動追加はなし
- 起動後であっても persona 毎のサンドボックスが自動追加されるべき
- ハードコードは極力廃止すべき

#### B-1: SandboxOrchestrator 実装

**新ファイル**: `nous/infrastructure/sandbox_orchestrator.py`

**責務**:
- 起動時: 全既存 persona の MCP コンテナが存在することを保証（冪等）
- 作成時: 新規 persona の MCP コンテナを `docker run` で作成・起動
- 削除時: persona の MCP コンテナを `docker stop` + `docker rm` で停止・削除
- 復旧時: 起動時に orphan コンテナを自動回収（`_adopt_orphaned()`）

**API**:
```python
class SandboxOrchestrator:
    def ensure(self, persona: str) -> bool: ...
    def remove(self, persona: str) -> bool: ...
    def sync_all(self, personas: Optional[list[str]] = None) -> dict[str, str]: ...
    def shutdown(self) -> None: ...
    def get_url(self, persona: str) -> str: ...
```

**内部実装**:
- `docker.from_env()` で Docker SDK 利用
- コンテナ名: `opensandbox-mcp-{persona}`
- ポート割り当て: SHA256(persona) → 8401-8499 範囲（99 ポート）
- ネットワーク: `nous-network`（既存）
- レジストリ: `${DATA_ROOT}/sandbox_registry.json`（persona → container_id のマッピング、永続化）
- ラベル: `nous.managed=true`, `nous.persona={persona}`（orphan 検出用）

#### B-2: 既存 `docker-compose.yml` の改修

**削除**（ハードコード 3 サービス）:
- `x-opensandbox-mcp` アンカー
- `opensandbox-mcp-herta` / `opensandbox-mcp-alice` / `opensandbox-mcp-bob` サービス

**追加**（Nous に Docker socket）:
```yaml
  nous:
    # ... 既存設定 ...
    volumes:
      - ${DATA_ROOT}/app:/opt/nous/data
      - /var/run/docker.sock:/var/run/docker.sock  # NEW
```

**推奨**: 本番環境では `tecnativa/docker-socket-proxy` を間に挟む（最小権限化）

#### B-3: 統合ポイント

**`nous/main.py` (起動時)**:
```python
from nous.infrastructure.sandbox_orchestrator import SandboxOrchestrator

# AppContextRegistry 初期化後
orchestrator = SandboxOrchestrator(
    network="nous-network",
    data_dir=settings.data_dir,
)
personas_from_env = [p.strip() for p in os.environ.get("NOUS_PERSONAS", "").split(",") if p.strip()]
orchestrator.sync_all(personas_from_env if personas_from_env else None)
```

**`nous/api/http/routers/persona.py`**:
- `create_persona` の最後に `orchestrator.ensure(persona_name)` 追加
- `delete_persona` の `_cleanup_opensandbox_sandboxes` の後に `orchestrator.remove(persona)` 追加

**`nous/main.py` (停止時)**:
```python
import atexit
atexit.register(orchestrator.shutdown)
```

#### B-4: 環境変数の扱い

| 環境変数 | 扱い |
|----------|------|
| `NOUS_PERSONAS=herta,alice,bob` | **維持**: 起動時 sync の入力。空でも filesystem から自動検出。 |
| `NOUS_OPENDBOX_MCP_URL` | **維持**: 設定時は orchestrator バイパス、URL を全 persona で共有（後方互換）。 |
| `DOCKER_HOST` | **新規対応**: docker-py が `DOCKER_HOST` env で Podman 等にも接続可能。 |

#### B-5: 依存関係追加

`pyproject.toml`:
```toml
[project]
dependencies = [
    # ... 既存 ...
    "docker>=7.0.0",  # NEW: SandboxOrchestrator 用
]
```

#### B-6: テスト

**単体テスト** (`tests/unit/infrastructure/test_sandbox_orchestrator.py`):
- `test_ensure_creates_container`
- `test_ensure_idempotent`
- `test_remove_deletes_container`
- `test_remove_handles_not_found`
- `test_sync_all_converges_to_desired_state`
- `test_get_url_format`
- `test_port_assignment_collision_resistance`
- mock は `docker.from_env()` を patch

**統合テスト** (`tests/integration/test_sandbox_orchestrator_e2e.py`):
- testcontainers で実 Docker を使った E2E
- persona 作成 → コンテナ起動確認 → サンドボックス操作 → 削除 → コンテナ停止確認

### Priority C: 真の sandbox_list 分離（Oracle の指摘）

**問題**: per-persona MCP インスタンスでも `sandbox_list()` は全 sandbox を返す。
OpenSandbox バックエンドが persona 概念を持たないため、MCP インスタンス分離では完全分離にならない。

**修正方針（短期）**: Nous の MCP tool proxy 層で `sandbox_list` 結果をフィルタリング
- `MCPClientPool` に「現在の persona が所有する sandbox_id 一覧」を管理
- `sandbox_create` / `sandbox_kill` のフックで更新
- `sandbox_list` 呼び出し時にフィルタ適用

**工数**: 1-2 時間（Phase B の補助として実装推奨）

### Priority D: 設定振り分け Phase 2/3（保留中）

#### D-1: Phase 2 - WebUI 対応
- `nous/api/http/static/settings.js` に irodori_enabled / portrait_enabled / opensandbox_url の UI 追加
- `nous/api/http/static/chat.js` にチャット設定画面に反映
- `nous/api/http/routers/chat.py` field_name リストに 3 フィールド追加

#### D-2: Phase 3 - 二次改善
- P4: MCP サーバー「Reset to Defaults」ボタン
- P3: image_gen 命名統一の検討

### Priority E: T12 残課題

- opensandbox ツール名の検証: `chat.js:2698` の `opensandbox__execute_code` が正しい OpenSandbox MCP ツール名か未確認
- 標準ツール名は `sandbox_execute` / `sandbox_files` / `sandbox_create` / `sandbox_install` / `sandbox_reset` (docs/sandbox.md より)
- 実機テストで `sandbox_execute` 等の命名でアクセスできるか確認、必要なら `chat.js` を修正

## 📂 重要な参照ファイル

- `.agent/handoff/2026-07-11-1420.md` — 前回セッション (Phase B 完了)
- `.agent/handoff/2026-07-11-1930.md` — **本セッション (前 HANDOFF)**
- `.agent/memory/MEMORY.md` — 学習した知識・教訓（要更新）
- `.spec/PLAN.md` / `.spec/SPEC.md` / `.spec/TODO.md` — 仕様駆動開発の成果物
- `docker-compose.yml` — 本番 compose (要改修)
- `docker-compose.dev.yml` — dev compose (変更不要、B 完了後どうなるか要確認)
- `nous/infrastructure/sqlite/connection.py` — スキーママイグレーション参考パターン
- `nous/domain/chat_config.py` — P1-P5 実装の本体

## 🛠️ 実装順序の推奨

```
Step 1: Priority A-1, A-2, A-3（本番起動失敗修正）— 必須、これがないと検証不可
Step 2: Priority B-1, B-2, B-3, B-5（SandboxOrchestrator コア実装）— 動的プロビジョニング本体
Step 3: Priority B-4, B-6（環境変数・テスト）— B-1 の補助
Step 4: Priority C（sandbox_list 分離）— セキュリティ強化
Step 5: Priority D-1（WebUI 対応）— UX 改善
Step 6: Priority E（T12 実機確認）— 残課題解消
Step 7: Priority D-3（Phase 3 二次改善）— 後回し可
```

## 🚨 既知の落とし穴

- **P1-P5 修正で `import os` 漏れ**: `nous/application/chat/tools/builtin.py:128` の `os.environ.get(...)` 追加時に `import os` を入れ忘れた（commit `e00b27e` で修正済み）。CI で発覚。
- **既存テストの in-memory DB スキーマ**: `test_chat_service.py:317-372` と `test_compress_step.py:667-721` の `_make_db` ヘルパーが `chat_settings` をハードコードで作成。新カラム追加時は両方の修正が必要（過去 `sandbox_enabled` 削除でも同じ罠）。
- **`SandboxOrchestrator` の Docker socket**: dev compose では nous に直接マウント、本番では `tecnativa/docker-socket-proxy` を推奨。
- **per-persona MCP の `sandbox_list()` 分離は不完全**: Oracle レビューで明示。真の分離は Priority C で対応。

## 📊 テストカバレッジの現状

```
1646 passed / 7 skipped (Phase A/B + バグ修正 + 設定振り分け Phase 1 反映済み)
```

新規追加テスト（本日）:
- `tests/unit/domain/test_chat_config.py` — 18 件
- `tests/unit/api/mcp/test_tools_irodori.py` — 3 件
- `tests/unit/api/mcp/test_tools_portrait.py` — 3 件
- `tests/unit/api/http/routers/test_persona.py` — 9 件
- `tests/unit/test_chat_service.py` — 3 件 (P1-P5 追加)
- `tests/integration/test_http_routers.py` — 4 件 (メッセージ直接編集 API)

Priority B 着手時に追加すべきテスト:
- `tests/unit/infrastructure/test_sandbox_orchestrator.py` — 8 件 (上記 B-6 参照)
- `tests/integration/test_sandbox_orchestrator_e2e.py` — E2E 1-2 件
