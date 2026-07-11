# MCP Hub: デフォルト MCP サーバーのシード登録機能

## 要件（ユーザーからの指示）
- MCP Hub 初回起動時に、6つの推奨 MCP サーバーを自動登録
- すでにサーバーが登録されていれば何もしない（ユーザー環境の上書き禁止）
- Puppeteer 用に Chromium を Docker イメージに追加
- docker-compose.yml に Brave Search API キーのコメント追加
