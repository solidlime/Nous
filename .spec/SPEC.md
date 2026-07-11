# MCP Hub デフォルトサーバーシード機能 仕様

## 変更ファイル
- `mcp-hub/src/mcp_hub/registry.py`
- `mcp-hub/Dockerfile`
- `docker-compose.yml`

## registry.py
- `DEFAULT_SERVERS` 定数をモジュールレベルで定義（6件）
- `init()` にシード処理追加: テーブル作成後、`list_servers()` が空の場合のみ `DEFAULT_SERVERS` を全件登録
- シード失敗はサーバー単位でログ出力、全体の停止はしない
- `import logging` 追加、ロガー名は `__name__`

## Dockerfile
- Node.js インストール後、Chromium + chromium-sandbox を apt インストール
- `PUPPETEER_SKIP_DOWNLOAD=true`, `PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium` を ENV 設定
- apt-get clean は既存パターン通り `rm -rf /var/lib/apt/lists/*`

## docker-compose.yml
- mcp-hub サービスの environment に Brave Search API キーのコメント追加
- 実際の値は本番環境で直接設定 or .env 経由
