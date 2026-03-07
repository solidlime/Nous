# Nous

**Nous（ヌース）** — AIキャラクター自律稼働フレームワーク。

記憶・心理モデル・自律エージェントを統合し、キャラクターとしての一貫した人格を持つAIを動かすシステム。

## 起動方法

```bash
# Qdrant 起動（必須）
docker-compose up -d qdrant

# サーバー起動（MCP + REST API + WebSocket）
python main.py
```

起動後のエンドポイント:
- ダッシュボード: http://localhost:26263/dashboard
- チャット UI: http://localhost:26263/chat
- 設定画面: http://localhost:26263/settings
- MCP Server: http://localhost:26263/mcp

## アーキテクチャ

```
main.py
├── nous_mcp/        FastMCP サーバー + ツール群
├── agent/           自律エージェント層（AgentLoop）
├── psychology/      心理モデル層（感情・ドライブ・性格）
├── memory/          記憶コア（SQLite + Qdrant）
├── llm/             LLM ルーター（ollama/claude/openrouter）
├── elevation/       記憶の昇華（LLM 再体験生成）
├── api/             REST + WebSocket ルーター
└── output/          出力アダプター（Discord/Voice/Avatar）
```

詳細は [CLAUDE.md](./CLAUDE.md) を参照。
