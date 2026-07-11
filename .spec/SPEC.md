# SPEC: Nous 軽量化 + MCP ハブ化

## 1. 目的
- compose 構成を 6→2 に簡素化（qdrant + nous のみ）
- 未使用外部サービス（searxng, opensandbox, playwright）を完全削除
- Docker イメージに Node.js + uv を追加し、汎用 MCP ハブとして機能させる
- チャットUI の MCP サーバー登録機能は維持・強化

---

## 2. Docker Compose 変更

### 2.1 docker-compose.yml
**削除するサービス（4つ）**:
- `searxng-init` (全行)
- `searxng` (全行)
- `playwright` (全行)
- `opensandbox` (全行)

**削除する設定**:
- `configs.opensandbox-config` ブロック
- `volumes.opensandbox-config` ブロック
- `networks` ブロック（不要なら）

**nous サービス変更**:
- `depends_on` から `searxng` を削除（qdrant のみ残す）
- `environment.NOUS_SEARXNG_URL` を削除
- `volumes` から `/var/run/docker.sock:/var/run/docker.sock` を削除（sandbox_orchestrator 削除に伴う）
- sandbox-mcp 関連コメント削除

### 2.2 docker-compose.dev.yml
- 変更不要（nous サービスのオーバーライドのみ、searxng 参照なし）

---

## 3. Dockerfile 再構築

### 3.1 ベースイメージ
- Builder: `python:3.12-slim`
- Runtime: `python:3.12-slim` + Node.js

### 3.2 Builder ステージ変更
```
# 削除: torchvision, torchaudio
# 維持: torch (sentence-transformers の間接依存)
# 追加: uv インストール
```
- `pip install torch --index-url https://download.pytorch.org/whl/cpu` (torchvision/torchaudio 除去)
- `pip install uv`
- `uv pip install --system -r requirements.txt` (pip → uv 移行)

### 3.3 Runtime ステージ変更
**apt パッケージ追加**:
- `nodejs`, `npm` (Node.js LTS: MCP サーバー実行用)
- `git` (npm パッケージの git 依存対応)
- `wget` (汎用ユーティリティ)
- `build-essential` の一部 (`gcc`, `g++`, `make`: native addon ビルド用)

**apt パッケージ維持**:
- `curl` (healthcheck)
- `tzdata` (タイムゾーン)
- `tesseract-ocr`, `tesseract-ocr-jpn` (PDF OCR)

**削除**:
- pip/setuptools 削除処理: **削除しない**（ユーザーが `pip install` する可能性があるため）

### 3.4 uv のバイナリ保持
- Builder で `pip install uv` → Runtime に COPY されるので uv CLI が使える

---

## 4. コード変更: searxng 依存削除

### 4.1 `nous/application/chat/tools/builtin.py`
- `_handle_search()` 関数（約70行）を完全削除
- `TOOL_DISPATCH` 辞書から `"search": _handle_search` エントリ削除
- searxng 関連 import（httpx? → 他でも使ってたら維持）削除

### 4.2 `nous/api/mcp/tools.py`
- `search` ツール定義を削除
- `_handle_search` 呼び出しを削除
- NOTE: `_tool_search.py` があるならそちらも確認

### 4.3 `nous/main.py`
- searxng health check コードブロック削除（約10行）
- `status["services"]["searxng"]` 削除
- `SEARXNG_URL` 関連の env 参照削除

### 4.4 `nous/config/settings.py`
- `searxng_url: str = "http://localhost:8080"` 削除

### 4.5 `nous/config/runtime_config.py`
- `searxng_url` エントリ削除

### 4.6 `nous/infrastructure/sqlite/connection.py`
- `searxng_url TEXT` カラム削除（スキーマ定義 + マイグレーション）
- 注意: DB マイグレーションとして安全に処理する必要あり

### 4.7 ツール一覧系
- `list_skills` / tool list に `search` が含まれていないか確認

---

## 5. コード変更: opensandbox 依存削除

### 5.1 `nous/infrastructure/sandbox_orchestrator.py`
- **ファイルごと削除**

### 5.2 `nous/application/chat/tools/builtin.py`
- opensandbox 固有のツールルーティングコード削除
- **重要**: `__`区切りの汎用MCPルーティングは **削除しない**（ユーザー登録MCPサーバーのツール呼び出しに必須）
- 削除対象: opensandbox 専用の初期化/クリーンアップコード

### 5.3 `nous/domain/chat_config.py`
- `_get_default_mcp_servers()` 関数から opensandbox エントリを削除
- `ChatConfig.opensandbox_url` フィールド削除
- `DEFAULT_MCP_SERVERS` から playwright エントリ削除（playwright依存削除）
- 関数自体は維持（将来のデフォルトMCPサーバー用）

### 5.4 `nous/application/persona.py` (または該当ファイル)
- `_cleanup_opensandbox_sandboxes()` 削除
- 呼び出し元も削除

### 5.5 `nous/api/http/routers/chat.py`
- `ChatConfigUpdate` スキーマから `opensandbox_url` フィールド削除

### 5.6 `nous/api/http/sections/chat.py`
- OpenSandbox URL 入力欄の HTML ブロック削除（`<details data-category="extensions">` 内）

### 5.7 `nous/api/http/static/chat.js`
- `openSandboxUrl` 関連の変数/処理削除
- `chat-opensandbox-url` DOM 操作削除
- `opensandbox__sandbox_execute` 直接呼び出し削除

---

## 6. コード変更: playwright 依存削除

### 6.1 `nous/domain/chat_config.py`
- `_get_default_mcp_servers()` から playwright エントリ削除（#5.3と重複）

---

## 7. 変更しないもの（明示的維持）

### 7.1 汎用 MCP ルーティング
- `registry.py` の `is_mcp_tool()` : `"__" in tool_name` → **維持**
- `builtin.py` の `execute_tool()` MCP 転送 → **維持**
- `MCPClientPool` → **維持**
- チャットUI の MCP サーバー登録UI → **維持**

### 7.2 ツール
- `invoke_skill` → 維持（LLM呼び出しのみ）
- `memory_*` → 維持
- `image_generate` → 維持
- `read_pdf` → 維持

---

## 8. テスト更新

### 8.1 削除対象テスト
- `tests/unit/test_builtin_handlers.py`: searxng 関連テスト削除
- `tests/unit/domain/test_chat_config.py`: opensandbox URL テスト削除
- `tests/unit/domain/test_sandbox_ownership.py`: ファイルごと削除
- `tests/unit/infrastructure/test_sandbox_orchestrator.py`: ファイルごと削除
- `tests/unit/application/chat/tools/test_builtin.py`: opensandbox + playwright テスト削除
- `tests/unit/api/http/routers/test_persona.py`: opensandbox cleanup テスト削除

### 8.2 修正対象テスト
- `tests/unit/test_chat_service.py`: searxng_url / opensandbox_url 参照を削除

---

## 9. 検証項目

1. `docker compose up` で qdrant + nous のみ起動すること
2. nous の `/health` エンドポイントが正常に 200 を返すこと
3. MCP サーバー登録UI が正常に表示・動作すること
4. 既存ツール（memory, image_generate, read_pdf, invoke_skill）が動作すること
5. `docker compose down` で全サービスが正常終了すること
6. 全テストがパスすること
7. Docker イメージサイズが許容範囲であること
