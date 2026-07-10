# SPEC: ブラウザ・サンドボックス機能の外部移行

## REPLACE-BROWSER: ブラウザ機能の置き換え
- 旧: agent-browser CLI（npmパッケージ + Chrome依存、subprocess経由）
- 新: Playwright MCP（`mcr.microsoft.com/playwright/mcp` または npx起動）
- Nous側: 組み込みbrowserツールを削除し、外部MCPサーバーとして登録
- 永続化: ブラウザプロファイルを `${DATA_ROOT}/playwright` にホストマウント

## REPLACE-SANDBOX: サンドボックス機能の置き換え
- 旧: カスタムDockerコンテナ（`ghcr.io/solidlime/nous-sandbox`） + Linuxユーザー分離 + `docker exec` ベース
- 新: OpenSandbox（`opensandbox/server` + `opensandbox/execd` + `opensandbox-mcp`）
- Nous側: sandbox_execute/files/reset/context 全ツールを削除し、外部MCPサーバーとして登録
- 永続化: sandboxデータを `${DATA_ROOT}/opensandbox` にホストマウント
- ペルソナ分離: OpenSandboxのsandbox単位分離 + named volumes（PVC）

## DOCKER-INTEGRATION: Docker Compose構成
- 既存の `sandbox` サービス + `Dockerfile.sandbox` を削除
- Playwright MCP サービスを追加（SSEトランスポート、ポート8931）
- OpenSandbox Server サービスを追加（APIポート8090）
- OpenSandbox MCP サービスを追加（stdio または streamable-http、ポート8000）
- 全サービスにヘルスチェックとボリュームマウントを設定

## PERSONA-ISOLATION: ペルソナ分離
- OpenSandboxのsandbox単位でコンテナ分離（1ペルソナ = 1 sandbox）
- Docker named volumes でペルソナ別データ永続化
- ペルソナ名をsandbox_idまたはタグとしてマッピング

## WEBUI-INTEGRATION: WebUIチャット統合
- 既存の `/browser` スラッシュコマンド、BUILTIN_SKILLS を削除/更新
- MCPサーバー設定（`ChatConfig.mcp_servers`）にデフォルトで両サーバーを登録
- `#chat-mcp-json` UIで表示・編集可能な状態を維持

## CODE-CLEANUP: コード削除範囲
- `nous/application/sandbox/` モジュール全体
- `builtin.py` の `_handle_browser()` 関連
- `_tools_sandbox.py` 全体
- `tools.py` のsandbox/browser MCP登録
- `definitions.py` のsandbox/browserツール定義
- `Dockerfile.sandbox`
- `scripts/setup_agent_browser.sh`
- DockerfileのChrome/Node.js/agent-browser関連

## DOCS: ドキュメント更新
- `docs/sandbox.md` → OpenSandbox情報に更新
- `CLAUDE.md` のツール一覧更新
- `docs/llm_usage_guide.md` に新MCP構成を追記
