# CLAUDE.md

- セッション開始時に共通ルールである、AGENTS.mdを必ず読み込むこと。
- 読み込んだことを最初に報告すること
- コンテキスト削減のため serena skill を絶対に使用すること
- 以下は Claude Code 固有の差分のみ記載する

---

## コマンド

```bash
# サーバー起動
python main.py

# Qdrant 起動（必須）
docker-compose up -d qdrant

# テスト
python run_tests.py

# インポートチェック
python -c "from agent.loop import AgentLoop; print('OK')"

# DBマイグレーション（MemoryMCP → Nous）
python -m migrations.memorymcp_to_nous --source /path/to/memorymcp/data --target ./data --persona herta
```

起動後のエンドポイント:
- ダッシュボード: http://localhost:26263/dashboard
- チャット UI: http://localhost:26263/chat
- MCP Server: http://localhost:26263/mcp

## 重要な実装ルール

### インポート名前空間
ローカル MCP モジュールは `nous_mcp/`。`mcp/` は使わない（pip の `mcp` パッケージと衝突）。
```python
from nous_mcp.server import get_db_path, get_psychology_db_path, get_conversation_db_path
```

### DBパス解決
```python
get_db_path(persona)            → data/{persona}/memory.db
get_psychology_db_path(persona) → data/{persona}/psychology.db
get_conversation_db_path(persona) → data/{persona}/conversations.db
```

### EmotionalModel API
`update(event_type: str, intensity: float)` のみ。`update_from_text()` は存在しない。

### マルチペルソナ
`Authorization: Bearer {persona}` ヘッダーで切り替え。
`get_persona(request)` → Bearer → `PERSONA` 環境変数 → `config.default_persona` の順。

### LLM タスク種別

| task_type | プロバイダー | 用途 |
|-----------|------------|------|
| `consciousness` | ollama | 意識ティック判断 |
| `discord_reply` | ollama | Discord/Web 返答 |
| `memory_elevation` | claude | 記憶の昇華 |
| `anniversary` | claude | 記念日発話 |
| `summarization` | openrouter | スレッド要約 |

### デフォルト設定
- ポート: `26263`（MemoryMCP は 26262）
- Qdrant ポート: `6334:6333`
- タイムゾーン: `Asia/Tokyo`
- デフォルトペルソナ: `herta`
- Qdrant コレクション prefix: `nous_`
