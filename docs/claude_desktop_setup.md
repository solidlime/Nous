# Claude Desktop セットアップ

## アーキテクチャ概要

```text
[Claude Desktop] --stdio--> [mcp-proxy / mcp-remote] --HTTP--> [nous サーバ]
```

Memory MCP サーバは常に外部 HTTP サーバとして動作します。
Claude Desktop は **stdio トランスポートのみ**サポートしているため、
stdio ↔ HTTP ブリッジを経由して外部サーバに接続します。

> **注意**: 外部サーバは `nous.main` を `streamable-http` モードで常時起動しておく必要があります。

---

## 方法 1: mcp-remote（推奨・Node.js/npx）

`mcp-remote` は Claude が公式に推奨するブリッジです。

### インストール不要（npx で実行）

```json
{
  "mcpServers": {
    "nous": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "http://<server-ip>:26262/mcp",
        "--header", "Authorization:Bearer herta"
      ]
    }
  }
}
```

### Windows (wsl 経由)

```json
{
  "mcpServers": {
    "nous": {
      "command": "wsl",
      "args": [
        "-e", "bash", "-c",
        "npx -y mcp-remote http://<server-ip>:26262/mcp --header 'Authorization:Bearer herta'"
      ]
    }
  }
}
```

---

## 方法 2: mcp-proxy（Python）

Python 環境がある場合は `mcp-proxy` が使えます。

### インストール

```bash
uv tool install mcp-proxy
# または
pip install mcp-proxy
```

### 設定

```json
{
  "mcpServers": {
    "nous": {
      "command": "mcp-proxy",
      "args": [
        "http://<server-ip>:26262/mcp"
      ],
      "env": {
        "MCP_PROXY_HEADERS": "Authorization=Bearer herta"
      }
    }
  }
}
```

---

## 方法 3: Settings → Connectors（Pro/Max/Team/Enterprise）

Claude Desktop の設定画面から直接 HTTP リモートサーバーを追加できます。

1. Claude Desktop → **Settings** → **Connectors**
2. **+ Add custom connector** をクリック
3. 以下を入力:
   - **URL**: `http://<server-ip>:26262/mcp`
   - **Headers**: `Authorization: Bearer herta`

> この方法は `claude_desktop_config.json` への記述不要で、最もシンプルです。
> ただし Claude Pro/Max 以上のプランが必要です。

---

## ペルソナ指定

どの方法でも `Authorization: Bearer <persona>` ヘッダーでペルソナを指定します。

| ペルソナ | ヘッダー値 |
|----------|-----------|
| herta | `Authorization: Bearer herta` |
| default | `Authorization: Bearer default` |

---

## 設定ファイルの場所

| OS | パス |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/claude/claude_desktop_config.json` |

---

## サーバー側の起動確認

Claude Desktop から接続する前に、外部サーバーが起動済みであることを確認:

```bash
# Docker Compose で起動
docker compose up -d

# または直接起動
python -m nous.main

# ヘルスチェック
curl http://<server-ip>:26262/health
```

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| ツールが表示されない | mcp-remote/mcp-proxy のログを確認。サーバーが起動しているか確認 |
| `ECONNREFUSED` | サーバー IP・ポートを確認（Docker の場合 localhost ではなくホスト IP を使用） |
| ペルソナが切り替わらない | `Authorization: Bearer <persona>` ヘッダーの値を確認 |
| `npx` が見つからない | Node.js をインストール（`node -v` で確認） |
| RAG エラー | Qdrant が起動しているか確認（`docker compose up -d`） |
