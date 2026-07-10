# Browser & Sandbox 外部MCP移行 + WebUIバグ修正 実装計画

> **For agentic workers:** REQUIRED: Use @fixer and @designer subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 組み込みのブラウザ（agent-browser）とサンドボックス（カスタムDockerコンテナ）を削除し、Playwright MCP + OpenSandbox に外部MCP移行。並行してWebUI監査で発見されたバグを修正。

**Architecture:** Playwright MCP と OpenSandbox を独立した Docker サービスとして起動。Nous の既存 `MCPClientPool` + `ChatConfig.mcp_servers` 機構で統合。ツールは `playwright__browser_navigate` / `opensandbox__sandbox_create` 形式で LLM から透過呼び出し。

**Tech Stack:** Docker Compose, Playwright MCP（npx/stdio）, OpenSandbox（FastAPI + Docker runtime）, Python 3.12, FastMCP

**Review Strategy:** 各Chunk完了後 @oracle でレビュー。7 Chunks構成。

**Spec Reference:** `.spec/SPEC.md`

---
---

## Chunk 1: Dockerインフラ整備（削除+追加）

**Files:**
- Modify: `docker-compose.yml`
- Delete: `Dockerfile.sandbox`
- Modify: `Dockerfile`（Chrome/Node.js/agent-browser削除）
- Delete: `scripts/setup_agent_browser.sh`

### Task 1.1: docker-compose.yml から sandbox サービス削除

- [ ] **Step 1: sandboxサービス（L98-117）を削除し、sandbox関連の環境変数・ボリュームコメントを削除**

対象行:
- L77-87: `nous` サービスのsandbox関係コメント・環境変数（NOUS_SANDBOX__* / NOUS_AGENT_BROWSER_PATH / NOUS_SANDBOX__HOST_DATA_ROOT）
- L98-117: `sandbox` サービス全体
- L62-63: `nous` の `/var/run/docker.sock` ボリュームマウント（sandbox用、他用途がなければ削除）

以下の環境変数は維持: NOUS_QDRANT__URL, SEARXNG_URL, LANG
以降の新しい環境変数用の場所を確保。

- [ ] **Step 2: 修正後のdocker-compose.yml構文チェック**

```bash
docker compose -f docker-compose.yml config --quiet
```

### Task 1.2: docker-compose.yml に Playwright MCP サービス追加

- [ ] **Step 3: Playwright MCPサービスを追加**

`nous` サービスの前に以下を挿入:

```yaml
  playwright:
    image: mcr.microsoft.com/playwright/mcp:latest
    container_name: playwright
    ports:
      - "8931:8931"
    volumes:
      - ${DATA_ROOT}/playwright:/ms-playwright
    environment:
      TZ: Asia/Tokyo
    command: >
      node /app/cli.js
        --headless
        --browser chromium
        --no-sandbox
        --user-data-dir /ms-playwright
        --port 8931
        --host 0.0.0.0
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:8931/health', r => {process.exit(r.statusCode === 200 ? 0 : 1)})"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

依存: なし（独立サービス）
Playwright MCP は `nous` サービスの `depends_on` に追加不要（Nous側のMCPClientPoolが動的接続するため）。

### Task 1.3: docker-compose.yml に OpenSandbox Server + MCP サービス追加

- [ ] **Step 4: OpenSandbox Server と MCP 転送サービスを追加**

```yaml
  opensandbox:
    image: opensandbox/server:latest
    container_name: opensandbox
    ports:
      - "8090:8090"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ${DATA_ROOT}/opensandbox/volumes:/var/lib/opensandbox/volumes
      - opensandbox-config:/etc/opensandbox
    environment:
      TZ: Asia/Tokyo
      SANDBOX_CONFIG_PATH: /etc/opensandbox/config.toml
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    configs:
      - source: opensandbox-config
        target: /etc/opensandbox/config.toml

  opensandbox-mcp:
    image: python:3.11-slim
    container_name: opensandbox-mcp
    ports:
      - "8000:8000"
    command: >
      sh -c "pip install --no-cache-dir opensandbox-mcp &&
             opensandbox-mcp --transport streamable-http
                            --domain opensandbox:8090
                            --protocol http"
    environment:
      TZ: Asia/Tokyo
    restart: unless-stopped
    depends_on:
      opensandbox:
        condition: service_healthy
    # NOTE: API key不要（Nous内部ネットワーク経由のため）

configs:
  opensandbox-config:
    content: |
      [server]
      host = "0.0.0.0"
      port = 8090

      [runtime]
      type = "docker"
      execd_image = "opensandbox/execd:latest"

      [docker]
      network_mode = "bridge"
      host_ip = "host.docker.internal"
      drop_capabilities = ["AUDIT_WRITE", "MKNOD", "NET_ADMIN", "NET_RAW", "SYS_ADMIN", "SYS_MODULE", "SYS_PTRACE", "SYS_TIME", "SYS_TTY_CONFIG"]
      no_new_privileges = true

      [store]
      type = "sqlite"
      path = "/var/lib/opensandbox/opensandbox.db"

volumes:
  opensandbox-config:
```

OpenSandbox MCP のエンドポイント: `http://opensandbox-mcp:8000/mcp`（streamable-http）

### Task 1.4: Dockerfile クリーンアップ + Dockerfile.sandbox 削除

- [ ] **Step 5: Dockerfile から agent-browser 関連を削除**

対象:
- Node.js インストール行（`curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs`）
- Chrome依存ライブラリ群（`libnspr4 libnss3 libatk-bridge2.0-0 ...`）
- `COPY scripts/setup_agent_browser.sh /usr/local/bin/` 行
- `RUN chmod +x /usr/local/bin/setup_agent_browser.sh` 行
- `ENTRYPOINT ["/usr/local/bin/setup_agent_browser.sh"]` → `CMD` のままにする
- `NOUS_AGENT_BROWSER_PATH` 関連の ENV 設定
- `.agent-browser` 関連のシンボリックリンク設定

ENTRYPOINT を削除、CMD を直接 `["python", "-m", "nous.main"]` に。

- [ ] **Step 6: Dockerfile.sandbox を削除**

```bash
rm Dockerfile.sandbox
```

- [ ] **Step 7: scripts/setup_agent_browser.sh を削除**

```bash
rm scripts/setup_agent_browser.sh
```

### Task 1.5: .env 更新

- [ ] **Step 8: NOUS_SANDBOX__* と NOUS_AGENT_BROWSER_PATH 関連の環境変数を .env / .env.example から確認・削除**

```bash
grep -E 'NOUS_SANDBOX|NOUS_AGENT_BROWSER' .env .env.example 2>/dev/null
```
該当行があれば削除。なければスキップ。

### Task 1.6: コミット

- [ ] **Step 9: コミット**

```bash
git add docker-compose.yml Dockerfile .env .env.example
git rm Dockerfile.sandbox scripts/setup_agent_browser.sh
git commit -m "feat(docker): add Playwright MCP + OpenSandbox services, remove old sandbox container and agent-browser setup"
```

---
---

## Chunk 2: バックエンド — ブラウザコード削除

**Files:**
- Modify: `nous/application/chat/tools/builtin.py`
- Modify: `nous/application/chat/tools/definitions.py`
- Modify: `nous/api/mcp/tools.py`
- Modify: `nous/config/settings.py`
- Modify: `nous/config/runtime_config.py`

### Task 2.1: builtin.py から `_handle_browser()` と `_find_agent_browser()` を削除

- [ ] **Step 1: `_handle_browser()` (L166-348 相当) と `_find_agent_browser()` (L399-440 相当) を削除**

注意: `_handle_search`, `_handle_image_generate`, `_handle_read_pdf`, `_handle_list_skills` は残す。browser関連のimport（`_find_agent_browser` の内部で使っている `os`, `shutil`, `Settings` など）は他で使われているか確認してから削除。

- [ ] **Step 2: ruff check 確認**

```bash
cd nous && ruff check nous/application/chat/tools/builtin.py
```

### Task 2.2: tools.py から browser MCP ツール登録を削除

- [ ] **Step 3: `nous/api/mcp/tools.py` の `@_tool("browser")` デコレータブロック全体（L485-533 相当）を削除**

TOOL_DISPATCH も browser エントリがあれば削除。

- [ ] **Step 4: `_tools_helpers.py` に `_handle_browser` import があれば削除**

```bash
grep -n 'browser\|_handle_browser' nous/api/mcp/tools.py nous/api/mcp/_tools_helpers.py
```

### Task 2.3: definitions.py から browser 定義を削除

- [ ] **Step 5: `definitions.py` の `CONDITIONAL_TOOLS["browser"]` 行（L35相当）を削除**

- [ ] **Step 6: `definitions.py` の `ToolDefinition(name="browser", ...)` ブロック（L271-309 相当）を削除**

### Task 2.4: settings.py / runtime_config.py から browser 設定を削除

- [ ] **Step 7: `settings.py` の `agent_browser_path: str = ""` 行削除**

- [ ] **Step 8: `runtime_config.py` の `agent_browser_path` エントリ削除**

- [ ] **Step 9: `chat_config.py` に browser 関連フィールドがあれば削除**

```bash
grep -n browser nous/domain/chat_config.py
```

### Task 2.5: コミット

- [ ] **Step 10: 全テスト実行**

```bash
pytest tests/ -x -q --ignore=tests/integration --tb=short 2>&1 | tail -20
```
削除で壊れるテストがあればリストアップ（Chunk 6で修正）。

- [ ] **Step 11: コミット**

```bash
git add -A
git commit -m "refactor: remove built-in browser tool (migrated to Playwright MCP)"
```

---
---

## Chunk 3: バックエンド — サンドボックスコード削除

**Files:**
- Delete: `nous/application/sandbox/` ディレクトリ全体
- Delete: `nous/api/mcp/_tools_sandbox.py`
- Modify: `nous/api/mcp/tools.py`
- Modify: `nous/application/chat/tools/definitions.py`
- Modify: `nous/application/chat/tools/__init__.py`
- Modify: `nous/application/chat/tools/builtin.py`（sandboxハンドラ）
- Modify: `nous/application/chat/service.py`
- Modify: `nous/domain/chat_config.py`（モデル + Repository SQL 7箇所）
- Modify: `nous/infrastructure/sqlite/connection.py`（テーブル定義 + Repository SQL）
- Modify: `nous/config/settings.py`
- Modify: `nous/config/runtime_config.py`
- Modify: `nous/main.py`
- Modify: `nous/api/http/routers/chat.py`（sandbox REST エンドポイント8つ削除）

### Task 3.1: sandbox コアモジュール削除

- [ ] **Step 1: `nous/application/sandbox/` 全体を削除**

```bash
rm -rf nous/application/sandbox/
```

- [ ] **Step 2: `nous/api/mcp/_tools_sandbox.py` を削除**

```bash
rm nous/api/mcp/_tools_sandbox.py
```

- [ ] **Step 3: import エラー確認**

```bash
cd nous && python -c "import nous.api.mcp.tools" 2>&1
grep -rn "sandbox\|_tools_sandbox" nous/api/mcp/tools.py nous/application/chat/ nous/main.py
```

### Task 3.2: tools.py から sandbox MCP 登録を削除

- [ ] **Step 4: `nous/api/mcp/tools.py` の sandbox 関連コードを削除**

対象:
- `_tools_sandbox` からの import行（L53-57相当）
- `get_settings().sandbox.enabled` 条件ブロック（L372-417相当）全体
- sandbox_execute, sandbox_files, sandbox_reset, sandbox_context の `@_tool` デコレーション
- TOOL_DISPATCH の sandbox エントリ

### Task 3.3: definitions.py から sandbox 定義を削除

- [ ] **Step 5: `definitions.py` の `SANDBOX_TOOLS` 変数（L402-497相当）とその参照を削除**

```bash
grep -n 'SANDBOX_TOOLS\|sandbox_execute\|sandbox_files\|sandbox_reset\|sandbox_context' nous/application/chat/tools/definitions.py
```

### Task 3.4: service.py から sandbox 参照を削除

- [ ] **Step 6: `service.py` L82-83 の `SANDBOX_TOOLS` 追加ロジックを削除**

```bash
grep -n 'sandbox\|SANDBOX' nous/application/chat/service.py
```
`sandbox_enabled` チェックと `SANDBOX_TOOLS` 組み込みを削除。

### Task 3.5: builtin.py から sandbox ハンドラを削除

- [ ] **Step 7: sandbox実行ハンドラ関数を削除**

```bash
grep -n 'sandbox\|_is_sandbox' nous/application/chat/tools/builtin.py
```
sandbox_execute/files/reset/context ハンドラ（L115-163相当）と `_is_sandbox_path()`（L629-683相当）を削除。

### Task 3.6: chat_config.py から `sandbox_enabled` を完全削除（全7箇所）

⚠️ **最も危険な変更**: 1フィールド削除に見えて、Repository の SQL/行マッピング/値タプルに広範な影響がある。

- [ ] **Step 8a: モデルフィールド削除 — `nous/domain/chat_config.py` L79の `sandbox_enabled: bool = True` を削除**

- [ ] **Step 8b: Repository.get() の SELECT カラムリストから `sandbox_enabled` を削除**

`nous/infrastructure/sqlite/connection.py:266` 付近の SELECT 文の53番目のカラムを削除。

- [ ] **Step 8c: Repository.get() の行マッピングを更新**

`nous/infrastructure/sqlite/connection.py:310` 付近の `sandbox_enabled=bool(row[26])` を削除。後続カラムのインデックスを1つずつずらす。

- [ ] **Step 8d: Repository.save() の INSERT カラムリストから `sandbox_enabled` を削除**

`nous/infrastructure/sqlite/connection.py:353` 付近。

- [ ] **Step 8e: Repository.save() の UPSERT カラムリストから `sandbox_enabled` を削除**

`nous/infrastructure/sqlite/connection.py:392` 付近。

- [ ] **Step 8f: Repository.save() の values タプルから `int(config.sandbox_enabled)` を削除**

`nous/infrastructure/sqlite/connection.py:446` 付近。後続の値インデックスも調整。

- [ ] **Step 8g: テーブル定義から `sandbox_enabled` カラムを削除**

`nous/infrastructure/sqlite/connection.py:209` 付近の `sandbox_enabled INTEGER DEFAULT 1` を CREATE TABLE 文から削除。
**注意**: 既存DBのマイグレーションは `ALTER TABLE chat_settings DROP COLUMN sandbox_enabled` が必要だが、SQLite は DROP COLUMN 非対応バージョンがある。新しいカラム定義なしで CREATE TABLE し直すか、単に無視する（既存DBにカラムが残っても読み取り時に無視される）。pydanticモデルからフィールドを消せば、Repositoryが読み取ろうとしなくなる。

- [ ] **Step 8h: tools/__init__.py の import 修正**

`nous/application/chat/tools/__init__.py` L4 の `from ...definitions import MEMORY_TOOLS, SANDBOX_TOOLS` から `SANDBOX_TOOLS` を削除。`__all__` にもあれば削除。

### Task 3.7: settings.py / runtime_config.py / main.py から sandbox 設定を削除

- [ ] **Step 9: settings.py の `SandboxConfig` クラス定義と `sandbox` フィールドを削除**

```bash
grep -n 'SandboxConfig\|sandbox' nous/config/settings.py
```

- [ ] **Step 10: runtime_config.py の sandbox セクションを削除**

- [ ] **Step 11: main.py の sandbox 起動コードを削除**

```bash
grep -n 'sandbox\|_ensure_sandbox' nous/main.py
```
sandbox コンテナ確認、ヘルスチェック表示、atexit session close を削除。

### Task 3.8: コミット（sandbox REST API削除前）

- [ ] **Step 12: 全テスト実行で sandbox 参照エラー確認**

```bash
grep -rn "sandbox" tests/ --include="*.py" | grep -v __pycache__ | head -20
```

### Task 3.9: routers/chat.py から sandbox REST API エンドポイントを削除

⚠️ sandbox モジュール削除後にこのファイルを import すると `ModuleNotFoundError` でクラッシュするため、sandbox コード削除と同じコミットで処理する必要がある。

- [ ] **Step 13: `nous/api/http/routers/chat.py` の sandbox エンドポイント（L313-762 相当）を削除**

対象エンドポイント（約450行）:
- `POST /sandbox/upload`
- `GET /sandbox/files`
- `POST /sandbox/execute`
- `POST /sandbox/install`
- `POST /sandbox/reset`
- `DELETE /sandbox/files/{path}`
- `GET /sandbox/file/read`
- `POST /sandbox/file/write`

以下も同時に削除:
- `from nous.application.sandbox.service import get_sandbox_session` import行
- `from nous.domain.chat_config import ChatConfig` の sandbox 関連参照
- `chat_cfg.sandbox_enabled` を参照しているコード

- [ ] **Step 13a: `attachment_upload` エンドポイントのパス名を修正**

`routers/chat.py` L371 の `Path(settings.data_root) / "sandbox" / persona / "uploads"` の `"sandbox"` を `"uploads"` に変更。
L405 の `workspace_path: f"/sandbox/uploads/{filename}"` も同様に `/uploads/{filename}` に変更。
sandboxが無くなったのに "sandbox" ディレクトリにファイル保存する矛盾を解消する。

- [ ] **Step 13a: `attachment_upload` のディレクトリ名を `"sandbox"` → `"uploads"` にリネーム**

`routers/chat.py` L371 の `Path(settings.data_root) / "sandbox" / persona / "uploads"` → `Path(settings.data_root) / "uploads" / persona`
L405 の `workspace_path: "/sandbox/uploads/{filename}"` → `"/uploads/{filename}"`

- [ ] **Step 14: `field_name` リストから `"sandbox_enabled"` を削除（L72）**

Chunk 5 Step 7 で追加する3フィールドの前に、まず削除を実施。

### Task 3.10: コミット

- [ ] **Step 15: コミット**

```bash
git add -A
git commit -m "refactor: remove built-in sandbox module (migrated to OpenSandbox MCP)"

---
---

## Chunk 4: 外部MCPサーバー設定の追加

**Files:**
- Modify: `nous/application/chat/service.py`（デフォルトMCPサーバー設定）
- Create/Modify: `.env.example`（MCP設定のデフォルト値 or コメント）

### Task 4.1: デフォルトMCPサーバー設定を ChatConfig に追加

- [ ] **Step 1: service.py で、ペルソナ新規作成時のデフォルト MCP サーバー設定を追加**

`ChatService.__init__()` または新規ペルソナ設定作成ロジックで、`mcp_servers` のデフォルト値に以下を含める:

```python
DEFAULT_MCP_SERVERS = [
    {
        "name": "playwright",
        "transport": "http",
        "url": "http://playwright:8931/mcp",
        "enabled": True,
    },
    {
        "name": "opensandbox",
        "transport": "http",
        "url": "http://opensandbox:8090/mcp",
        "enabled": True,
    },
]
```

注意: 既存ペルソナの `mcp_servers` は上書きしない（ユーザーが既に設定している可能性）。新規作成時のみ適用。

- [ ] **Step 2: Playwright MCP のエンドポイントパス確認**

Playwright MCP は v0.0.77 では SSEエンドポイントが `/sse`。実際のパスは起動して確認が必要。
暫定的に `http://playwright:8931/sse` をデフォルトとする。確認後に修正。

- [ ] **Step 3: OpenSandbox の MCP エンドポイント確認**

OpenSandbox MCP のデフォルトエンドポイントは streamable-http `/mcp` ポート8000。ただし独自ポートで起動する場合は要調整。
暫定的に `http://opensandbox-mcp:8000/mcp` とする（Chunk 1で別途MCPコンテナ追加の場合）。

### Task 4.2: コミット

- [ ] **Step 4: コミット**

```bash
git add -A
git commit -m "feat(mcp): add Playwright MCP and OpenSandbox MCP as default external servers"
```

---
---

## Chunk 5: WebUIフロントエンド更新

**Files:**
- Modify: `nous/api/http/static/chat.js`
- Modify: `nous/api/http/static/settings.js`
- Modify: `nous/api/http/static/base.js`
- Modify: `nous/api/http/sections/chat.py`
- Modify: `nous/api/http/routers/chat.py`

### Task 5.1: chat.js — ブラウザ/サンドボックス参照の完全削除

- [ ] **Step 1: BUILTIN_SKILLS から "browser" を削除（L586）**

```javascript
// Before
const BUILTIN_SKILLS = ["browser", "search"];
// After
const BUILTIN_SKILLS = ["search"];
```

- [ ] **Step 2: /browser スラッシュコマンドを削除（L1818-1821相当）**

`SLASH_COMMANDS` 配列から `/browser`, `/sandbox`, `/code` エントリを削除。

- [ ] **Step 2a: chat.js 内ハードコード welcome commands を削除**

L922 `/code`, L925 `/browser`, L927 `/sandbox` の `<span class="chat-welcome-cmd">` を削除。
（sections/chat.py のサーバーサイド版は Task 5.2 Step 5 で削除する）

- [ ] **Step 2a: JS側 welcome 表示から /browser, /sandbox, /code を削除**

`chat.js` L919-929 のハードコード welcome commands:
- L922: `/code` → 削除（sandbox依存のため。後日 OpenSandbox MCP 経由で再有効化）
- L925: `/browser` → 削除
- L927: `/sandbox` → 削除

`sections/chat.py`（サーバーサイドHTML）の同様の welcome commands は Task 5.2 Step 5 で削除済み。両方削除する必要がある。

- [ ] **Step 3: sandbox_enabled の全参照を削除**

以下の**9箇所**すべてを処理:

**設定・UI参照**:
- **L279**: `setChecked("chat-sandbox-enabled", cfg.sandbox_enabled === true)` → 削除
- **L280**: `onSandboxEnabledChange()` 呼び出し → 削除
- **L437**: `sandbox_enabled: getChecked("chat-sandbox-enabled")` → saveChatConfig payloadから削除

**ツール呼び出し連携**:
- **L2152-2156**: `sbEnabled` チェック → 削除（FILE_OP_TOOLS の条件分岐ごと削除）

**関数定義**:
- **L2464-2473**: `onSandboxEnabledChange()` 関数定義全体 → 削除
- **L2476-2477**: `sandboxAddArtifact()` 関数定義 → 削除（~20行）
- **L2498-2557**: `sandboxRunBlock()` 関数定義 → 削除（~60行、POST /sandbox/execute を直接呼び出すため404になる）
- **L2454-2461**: `sandboxLog()` 関数定義 → 削除（caAppendOutput 呼び出し含む）

**コードブロックレンダリング**:
- **L2651-2655**: `renderCodeBlock()` 内の `document.getElementById("chat-sandbox-enabled")?.checked` → 削除し `runnable` を常に `false` に
**L2476-2477**: `sandboxAddArtifact()` 関数定義 → 削除（到達不能になる）
**L2498-2557**: `sandboxRunBlock()` 関数定義 → 削除（`POST /sandbox/execute` を呼ぶため、残ると404エラー）
**L2458-2461**: `sandboxLog()` 内の `caAppendOutput()` 呼び出し → 削除（Chunk 5 Step 9 で対処）
**L2651-2655**: `renderCodeBlock()` 内の sandbox checkbox 参照 → `const sandboxEnabled = ...` 行を削除し、`runnable` は常に false に

- [ ] **Step 4: /code スラッシュコマンドの扱い**

`/code` → `handleSlashCommand("sandbox", ...)` を削除。後日 OpenSandbox MCP 統合後に再有効化できるようコメントアウト。

### Task 5.2: sections/chat.py — HTMLテンプレート更新

- [ ] **Step 5: サーバーサイドHTMLから browser/sandbox 参照を削除**

対象:
- **L96 付近**: `<span class="chat-welcome-cmd">/browser</span>` → 削除
- **L98 付近**: `<span class="chat-welcome-cmd">/sandbox</span>` → 削除
- **L445-448 付近**: sandbox トグルチェックボックスHTML（`id="chat-sandbox-enabled"`, `onchange="onSandboxEnabledChange()"`）→ 削除

### Task 5.2: WebUIバグ修正（監査で発見されたもの）

#### 🔴 CRITICAL: TTS音声再生バグ修正

- [ ] **Step 6: chat.js L2855 の `resp.ok` を修正**

```javascript
// Before (L2855)
if (resp.ok) {
  const audio = new Audio(`data:audio/wav;base64,${resp.audio_base64}`);
  ...
}
// After
const audioBase64 = resp.audio_base64 || resp.data?.audio_base64 || resp.result?.audio_base64;
if (audioBase64) {
  const audio = new Audio(`data:audio/wav;base64,${audioBase64}`);
  ...
}
```

APIレスポンスの実際のJSON構造を確認してから修正する。

#### 🔴 CRITICAL: 設定保存不可バグ修正

- [ ] **Step 7: `routers/chat.py` の `field_name` リストを修正**

L48-93 の tuple に対して:
- **削除**: `"sandbox_enabled"`（Chunk 3 Task 3.9 Step 14 で実施済み。未実施ならここで実施）
- **追加**: 以下の不足フィールド
```python
"context_use_llm_summary",
"episode_consolidation_enabled",
"episode_search_enabled",
```

同時に `nous/domain/chat_config.py` の `ChatConfig` データクラスにこれらのフィールドが存在するか確認し、なければ追加する。

#### 🟡 BUG: `renderMcpServerList()` 未定義

- [ ] **Step 8: `renderMcpServerList()` 関数を実装するか、呼び出しの代替処理を書く（L543）**

削除ボタン押下後のDOM更新。最も簡単な方法: `renderMcpJson(CHAT.mcpServers)` で全再描画する（既に同関数内にある）。

```javascript
// Before (L540-546)
removeBtn.addEventListener("click", () => {
  const servers = CHAT.mcpServers.filter(s => s.name !== serverName);
  CHAT.mcpServers = servers;
  renderMcpServerList(servers);
});
// After
removeBtn.addEventListener("click", () => {
  CHAT.mcpServers = CHAT.mcpServers.filter(s => s.name !== serverName);
  renderMcpJson(CHAT.mcpServers);  // 全再描画で代替
});
```

#### 🟡 BUG: `caAppendOutput()` 未定義

- [ ] **Step 9: `sandboxLog()` 内の `caAppendOutput()` 呼び出しを修正（L2458-2461）**

coding_agent.js に `caAppendOutput` 実装がないなら、sandboxログ転送を削除するか、`console.log` で代替。

```javascript
// Before
if (typeof caAppendOutput === "function") {
  caAppendOutput(text + "\n", type === "stderr" ? "stderr" : "stdout");
}
// After: 削除（sandbox自体が無くなるので）
// CodingAgentパネルは残すが、sandbox連携コードは削除
```

### Task 5.3: デッドコード削除

- [ ] **Step 10: `settings.js` の `DEPENDS_RULES = {}` と `applyDependsRules()` 呼び出しを削除**

- [ ] **Step 11: `base.js` の `toggleMobileNav()` を削除（L904）**

- [ ] **Step 12: `chat.py` の空の `render_chat_js()` メソッド（L500-506）を削除**

（他のレンダラーが参照していないことを確認してから）

- [ ] **Step 13: `base.js` の `animateCount()` 未使用部分を削除（L844）**

`data-animate-count` 属性を持つ要素がHTMLに存在しないことを確認済み。

### Task 5.4: MCP設定UI改善

- [ ] **Step 14: `chat-mcp-json` の `#add-mcp-btn` ボタン処理を確認**

現在: `addMcpServer()` が呼ばれ全JSON再パース。動作は正常。
ただし削除ボタンが効かない（Step 8 で修正）。

### Task 5.5: コミット

- [ ] **Step 15: コミット**

```bash
git add -A
git commit -m "fix(webui): remove browser/sandbox references, fix TTS playback, fix config save, fix MCP delete, clean dead code"
```

---
---

## Chunk 6: テスト修正

**Files:**
- Modify: `tests/unit/test_builtin_handlers.py`
- Modify: `tests/unit/test_mcp_sandbox.py`
- Modify: `tests/unit/test_chat_pipeline.py`
- Delete: `tests/unit/test_sandbox_user_manager.py`
- Delete: `tests/unit/test_sandbox_*.py` (sandbox関連テスト全般)

### Task 6.1: 削除されたコードのテストを特定・削除

- [ ] **Step 1: browser/sandbox テストファイルを特定**

```bash
grep -rl "browser\|sandbox\|agent_browser" tests/ --include="*.py" | grep -v __pycache__
```

- [ ] **Step 2: sandbox 専用テストファイルを削除**

```bash
rm tests/unit/test_sandbox_user_manager.py
rm tests/unit/test_mcp_sandbox.py  # sandbox MCP ツールのテスト
```

### Task 6.2: 他のテストファイルから sandbox/browser 参照を削除

- [ ] **Step 3: `test_builtin_handlers.py` から `_handle_browser` / sandbox 関連テストを削除**

- [ ] **Step 4: `test_chat_pipeline.py` から sandbox 関連テストを削除**

- [ ] **Step 5: 他のテストファイルの sandbox 参照削除**

### Task 6.3: テスト実行と確認

- [ ] **Step 6: 全テスト実行**

```bash
pytest tests/ -x -q --ignore=tests/integration --tb=short 2>&1 | tail -30
```
期待: sandbox/browser関連のimportエラーがなくなる。全テストパスを目指す。

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "test: remove sandbox and browser test suites"
```

---
---

## Chunk 7: ドキュメント更新 + 最終検証

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/sandbox.md`
- Modify: `docs/llm_usage_guide.md`
- Modify: `README.md`（必要な場合）
- Modify: `AGENTS.md`（本プロジェクトの）

### Task 7.1: ドキュメント更新

- [ ] **Step 1: `CLAUDE.md` のツール一覧から sandbox/browser ツールを削除し、新MCP構成を追記**

- [ ] **Step 2: `docs/sandbox.md` を OpenSandbox 構成に書き換え**

- [ ] **Step 3: `docs/llm_usage_guide.md` に Playwright MCP + OpenSandbox MCP の構成を追記**

MCPツールの追加・変更があった場合の必須更新。

- [ ] **Step 4: `.env.example` の古い sandbox/browser 変数をクリーンアップ**

### Task 7.2: 最終検証

- [ ] **Step 5: ruff check 全ファイル**

```bash
ruff check nous/ tests/
```

- [ ] **Step 6: 全テスト実行**

```bash
pytest tests/ -x -q --ignore=tests/integration --tb=short
```

- [ ] **Step 7: Docker Compose 設定構文チェック**

```bash
docker compose -f docker-compose.yml config --quiet
```

- [ ] **Step 8: コミット**

```bash
git add -A
git commit -m "docs: update documentation for Playwright MCP + OpenSandbox migration"
```

### Task 7.3: GitHub Actions CI確認

- [ ] **Step 9: push して CI パスを確認**

```bash
git push
```
GitHub Actions の結果を確認。失敗時はデバッグして修正。

---
---

## 付録A: 削除対象ファイル 完全リスト

| 操作 | ファイルパス |
|------|-------------|
| 削除 | `Dockerfile.sandbox` |
| 削除 | `scripts/setup_agent_browser.sh` |
| 削除 | `nous/application/sandbox/` ディレクトリ全体 |
| 削除 | `nous/api/mcp/_tools_sandbox.py` |
| 削除 | `tests/unit/test_sandbox_user_manager.py` |
| 削除 | `tests/unit/test_mcp_sandbox.py` |
| 修正 | `docker-compose.yml` |
| 修正 | `Dockerfile` |
| 修正 | `nous/application/chat/tools/builtin.py` |
| 修正 | `nous/application/chat/tools/definitions.py` |
| 修正 | `nous/application/chat/service.py` |
| 修正 | `nous/api/mcp/tools.py` |
| 修正 | `nous/config/settings.py` |
| 修正 | `nous/config/runtime_config.py` |
| 修正 | `nous/domain/chat_config.py` |
| 修正 | `nous/main.py` |
| 修正 | `nous/api/http/static/chat.js` |
| 修正 | `nous/api/http/static/settings.js` |
| 修正 | `nous/api/http/static/base.js` |
| 修正 | `nous/api/http/routers/chat.py` |
| 修正 | `nous/api/http/sections/chat.py` |
| 修正 | `CLAUDE.md` |
| 修正 | `docs/sandbox.md` |
| 修正 | `docs/llm_usage_guide.md` |

## 付録B: 後続タスク（今回の範囲外）

- OpenSandbox MCP のペルソナ分離を実際に構成・テスト（sandbox作成時に persona tag をメタデータとして付与）
- Playwright MCP のブラウザプロファイル永続化の実機確認
- `/code` スラッシュコマンドの新しい sandbox ツールへの再接続
- CodingAgent パネルと新 sandbox の連携方法の再設計
