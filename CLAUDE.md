# CLAUDE.md

- セッション開始時に共通ルールである、AGENTS.mdを必ず読み込むこと。
- 読み込んだことを最初に報告すること
- 以下は Claude Code固有の差分のみ記載する

---

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# サーバー起動（MCP + REST API + WebSocket 同時起動）
python main.py

# 起動後のエンドポイント
# ダッシュボード: http://localhost:26263/dashboard
# チャット UI:   http://localhost:26263/chat
# 設定画面:      http://localhost:26263/settings
# MCP Server:   http://localhost:26263/mcp

# DB マイグレーション（MemoryMCP からデータ移行）
python -m migrations.memorymcp_to_nous --source /path/to/memorymcp/data --target ./data --persona herta

# Qdrant（必須）
docker run -d -p 6334:6333 qdrant/qdrant
# または
docker-compose up -d qdrant

# Docker 全体起動
docker-compose up -d

# インポートテスト
python -c "from agent.loop import AgentLoop; print('OK')"
python -c "from output.discord_bot import DiscordBot; print('OK')"
```

## アーキテクチャ概要

**Nous** は「ヌース（知恵の星神）」の名を冠する AIキャラクター自律稼働フレームワーク。
MemoryMCP（ポート 26262）とは独立した別プロジェクト（ポート 26263）。

### エントリポイント

`main.py` がすべてのコンポーネントを初期化して FastAPI + FastMCP を起動する。
`lifespan()` でペルソナごとの AgentLoop・Discord Bot・忘却ワーカーをバックグラウンド起動。

### レイヤー構成

```
main.py
├── mcp/server.py         FastMCP(stateless_http=True) + get_persona()
├── mcp/tools/            MCPツール登録（memory/psychology/agent/avatar）
├── api/                  REST + WebSocket ルーター（FastAPI）
│   ├── chat_routes.py        /chat UI + /ws/chat/{persona}
│   ├── avatar_routes.py      /ws/avatar (Live2D) + /api/avatar/...
│   ├── dashboard_routes.py   / + /dashboard + /api/dashboard/...
│   ├── conversation_routes.py /api/conversations/...
│   ├── memory_routes.py      /api/memories/...
│   ├── agent_routes.py       /api/agent/...
│   └── settings_routes.py    /api/settings/...
│
├── agent/                自律エージェント層
│   ├── loop.py           AgentLoop — 2層自律トリガー（意識ティック + ドライブ閾値）
│   ├── event_bus.py      asyncio.PriorityQueue ベースのイベントバス
│   ├── scheduler.py      APScheduler — cron 強制ティック
│   ├── context_builder.py LLM コンテキスト構築（意識/イベント/Web用）
│   ├── action_executor.py アクション実行ディスパッチャー
│   └── tasks/            個別タスク（consciousness_tick, morning_greeting etc.）
│
├── psychology/           心理モデル層（SQLite永続）
│   ├── emotional_model.py 3層感情（表面/気分/慣性）→ `update(event_type, intensity)`
│   ├── drive_system.py   5ドライブ + 閾値トリガー
│   ├── personality.py    パーソナリティ特性（Big5 + 独自拡張）
│   ├── goal_manager.py   長期/短期目標
│   └── decision_engine.py 意思決定エンジン
│
├── memory/               記憶コア層（SQLite + Qdrant）
│   ├── db.py             MemoryDB — 24カラムスキーマ（昇華フィールド含む）
│   ├── conversation_db.py ConversationDB — cross-source 統合スレッド管理
│   ├── vector_store.py   VectorStore("nous_{persona}") — Qdrant
│   ├── forgetting.py     Ebbinghaus 忘却ワーカー
│   ├── blocks.py         Named Memory Blocks
│   └── user_state.py     Bi-temporal ユーザー状態
│
├── llm/                  LLM Router 層
│   ├── router.py         タスク種別でプロバイダーを切り替え（ollama/claude/openrouter）
│   ├── ollama_provider.py
│   ├── claude_provider.py
│   └── openrouter_provider.py
│
├── elevation/            記憶の昇華（LLM による再体験生成）
│   ├── elevate.py        MemoryElevator.elevate(entry)
│   └── batch_processor.py ElevationBatchProcessor.run_batch()
│
└── output/               出力アダプター
    ├── discord_bot.py    Discord Bot（受信→EventBus、送信）
    ├── voice_adapter.py  VOICEVOX HTTP API クライアント
    ├── webhook.py        Webhook 送受信
    └── avatar/
        ├── vtube_studio.py  VTube Studio WebSocket
        └── live2d_web.py    ブラウザ Live2D コントローラー
```

### 重要な設計決定

**名前空間の注意**: ローカルの MCP サーバーモジュールは `nous_mcp/` に配置。
pip の `mcp` パッケージ（`mcp.types` 等）と衝突しないように `mcp/` は使用しない。
インポートは必ず `from nous_mcp.server import ...` / `from nous_mcp.tools.xxx import ...` を使う。

**マルチペルソナ**: `Authorization: Bearer {persona}` ヘッダーで切り替え。
`get_persona(request)` → Bearer → PERSONA 環境変数 → `default_persona` config の順で解決。
各ペルソナは `data/{persona}/memory.db`, `data/{persona}/psychology.db`, `data/{persona}/conversations.db` に独立して保存。

**MCP サーバー**: FastMCP `stateless_http=True` で `/mcp` にマウント。
Claude Desktop 側の設定で `headers: {"Authorization": "Bearer herta"}` を指定するだけでペルソナ切り替え。

**Qdrant コレクション**: `nous_{persona}`（MemoryMCP の `memory_` プレフィックスと区別）。
ポートも Qdrant は `6334:6333` で公開（MemoryMCP の 6333 と競合しない）。

**2層自律トリガー**:
1. 意識ティック（15〜90分ランダム間隔）: LLM に状態を渡し「何かしたいか？」を問う
2. ドライブ閾値越え: DriveSystem の drive 値が閾値を超えたとき即座に発火

**AgentLoop.handle_web_message()**: チャット UI からの入力を処理。`ContextBuilder.build_web_context()` で会話履歴付きプロンプトを構築し、`LLMRouter.generate(task_type="discord_reply")` で返答生成。

**EmotionalModel**: `update(event_type: str, intensity: float)` で感情更新。
`event_type` は `"positive_interaction"`, `"negative_interaction"`, `"discovery"` 等の文字列。

### データパス解決

`mcp/server.py` の `get_db_path()` / `get_psychology_db_path()` / `get_conversation_db_path()` を使うこと:
```python
from mcp.server import get_db_path, get_psychology_db_path, get_conversation_db_path
```

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
- Qdrant ポート: `6334`
- タイムゾーン: `Asia/Tokyo`
- デフォルトペルソナ: `herta`
- リソースプロファイル: `low`（NAS DS920+ 向け最適化）
- Qdrant コレクションプレフィックス: `nous_`
