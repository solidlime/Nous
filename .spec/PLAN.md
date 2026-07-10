# PLAN: ブラウザ・サンドボックス機能の外部移行

## 目的
現在 Nous に組み込まれているブラウザ（agent-browser CLI）とサンドボックス（カスタムDockerコンテナ + Linuxユーザー分離）を削除し、
AIエージェント向けの最新外部プロジェクトに乗り換える。

## 選定結果
- ブラウザ → **Playwright MCP**（Microsoft公式、LLM不要、50+ツール、MCPネイティブ）
- サンドボックス → **OpenSandbox**（Alibaba、Apache-2.0、53MB軽量サーバー、MCP公式、ペルソナ分離可）

## 統合方式
- 両方とも外部MCPサーバーとしてDocker Composeで起動
- Nousの既存 `MCPClientPool` + `ChatConfig.mcp_servers` 機構で統合
- ツールは `{server_name}__{tool_name}` 形式でLLMから呼び出し可能
- WebUI設定画面のMCP JSONエディタで管理

## 注意
- サンドボックスはペルソナごとの分離必須（OpenSandboxのsandbox単位分離 + PVCで実現）
- データはホストマウント永続化（`${DATA_ROOT}/playwright` + `${DATA_ROOT}/opensandbox`）
- Docker Composeは1ファイル完結
