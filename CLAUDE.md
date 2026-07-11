# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Docker での起動（推奨）: nous + Qdrant を一括起動
docker-compose up -d

# 停止
docker-compose down

# ログ確認
docker-compose logs -f nous
docker-compose logs -f qdrant

# サーバー起動（ローカル開発時: Qdrant は別途起動が必要）
# volume mount 付きで起動しないと ./storage エラーになるので注意
docker run -d -p 6333:6333 -v "$(pwd)/data/qdrant:/qdrant/storage" qdrant/qdrant
python -m nous.main

# 全テスト実行（サーバーが localhost:26262 で起動中であること）
python run_tests.py

# 個別テスト
python run_tests.py --test http      # HTTP APIテスト
python run_tests.py --test search    # 検索精度テスト
python run_tests.py --test migrate   # DBスキーママイグレーション
python run_tests.py -v               # 詳細出力

# PyTorch CPU版（ローカル開発時のみ）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## アーキテクチャ

### エントリポイント

`nous.main` が唯一のエントリポイント（`python -m nous.main`）。FastMCPサーバーとして起動し、HTTP API（port 26262）も同時に公開する。Persona識別はBearerトークン、X-Personaヘッダー、または環境変数（PERSONA / NOUS_DEFAULT_PERSONA）で行う（優先順位: Bearer > X-Persona > 環境変数 > "default"）。

### レイヤー構成

```
nous/
├── main.py              # エントリポイント（FastMCP + HTTP）
├── config/settings.py   # Pydantic BaseSettings（NOUS_DATA_ROOT → 全パス自動導出）
├── domain/              # ドメイン層（ビジネスロジック）
├── infrastructure/      # インフラ層（SQLite / Qdrant / Embedding）
├── application/         # アプリケーション層（UseCases）
│   ├── chat/            # チャットサブパッケージ
│   │   ├── service.py        # ChatService / SSEストリーミング
│   │   ├── session_store.py  # SessionWindow / SessionManager（SQLite永続化）
│   │   ├── memory_llm.py     # MemoryLLM / run_memory_llm（自動記憶抽出）
│   │   └── tools.py          # MEMORY_TOOLS / execute_tool / invoke_skill
│   └── chat_service.py  # 後方互換 re-export のみ
├── api/mcp/             # MCP API層（ツール5本）
├── migration/           # スキーママイグレーション + インポーター
└── cli/                 # CLIツール
```

### 公開ツールAPI（19本）

| ツール | 主なパラメータ |
|--------|---------------|
| `get_context()` | なし（状態サマリー返却） |
| `memory_create(content, importance, tags, privacy_level, ...)` | 記憶作成。auto_emotionで現在感情を自動添付 |
| `memory_read(memory_key, limit, offset)` | 記憶読み取り・一覧 |
| `memory_update(memory_key, content, importance, tags, ...)` | 記憶更新（指定フィールドのみ変更） |
| `memory_delete(memory_key, query)` | 記憶削除（tombstone） |
| `memory_search(query, top_k, tags, date_range, min_importance, emotion, importance_weight, recency_weight, vector_weight, keyword_weight)` | ハイブリッド検索。mode廃止 — vector/keyword/importance/recency weightで調整。date_range: `"7d"`, `"30d"`, `"昨日"` |
| `memory_stats(top_n)` | 統計情報（件数・タグ分布・感情分布） |
| `update_context(emotion, emotion_intensity, physical_state, mental_state, environment, body_state, user_info, persona_info, ...)` | ペルソナ状態更新。`body_state`: `{fatigue, warmth, arousal, heart_rate, pain}` |
| `item_add(item_name, category, description, quantity, ...)` | インベントリにアイテム追加 |
| `item_equip(equipment, auto_add)` | 装備スロットにセット |
| `item_search(query, category)` | インベントリ検索 |
| `goal_manage(operation, content, importance, scope, memory_key)` | 目標管理。operation: `create/list/achieve/cancel`。scope: `self/interpersonal` |
| `invoke_skill(name, task)` | スキル実行（隔離LLMコンテキスト） |
| `persona_portrait()` | ポートレート画像生成（ComfyUI/DALL-E/Stability） |
| `irodori_tts(text, voice)` | 日本語TTS音声生成 |
| `search(query, num_results, language)` | Web検索（SearXNG経由） |
| `image_generate(prompt, size, quality, n, provider)` | 画像生成 |
| `read_pdf(path)` | PDF解析（テキスト・テーブル・画像抽出） |
| `list_skills()` | 登録スキル一覧 |

`memory_search()` の weight パラメータ: `vector_weight`（意味検索）/ `keyword_weight`（キーワード検索）/ `importance_weight` / `recency_weight` — 全て 0.0-1.0。

### Goals & Promises の管理

Goals と Promises は **memory タグ**で管理する。専用テーブルは廃止済み。

#### Tag規約

- goal:    `tags=["goal","active"]` / `["goal","achieved"]` / `["goal","cancelled"]`
- promise: `tags=["promise","active"]` / `["promise","fulfilled"]` / `["promise","cancelled"]`

#### ライフサイクル

```python
# 登録
memory_create(content="Goal text", tags=["goal","active"], importance=0.8)
memory_create(content="Promise text", tags=["promise","active"], importance=0.8)

# 達成/履行
memory_update(memory_key="...", tags=["goal","achieved"])
memory_update(memory_key="...", tags=["promise","fulfilled"])

# 中止
memory_update(memory_key="...", tags=["goal","cancelled"])

# 検索
memory_search(query="active goals", tags=["goal","active"])
memory_search(query="promises", tags=["promise","active"])
memory_search(query="goals", tags=["goal"])  # 全ステータス
```

- **確認方法**: `get_context()` の ACTIVE COMMITMENTS セクションに表示。`memory_search(query="active goals")` でも検索可能。
- **廃止**: `update_context(append_goals/append_promises/remove_goals/remove_promises)` は削除済み
- **非推奨**: `update_context(persona_info={"goals":...})` / `context_tags=["promise"]` / `context_tags=["goal"]` は使わない

### 永続化

- **SQLite**: 記憶エントリ・ユーザー状態・装備・Personaコンテキスト（`{data_root}/memory/<persona>/`配下）
- **Qdrant**: ベクトルストア（`memory_<persona>` コレクション）
- **設定**: `nous/config/settings.py` の Pydantic BaseSettings で管理。環境変数 `NOUS_*` プレフィックスで上書き可能。

### デフォルト設定値（主要なもの）

- データルート: `./data`（環境変数 `NOUS_DATA_ROOT`、Docker: `/data`）
- 埋め込みモデル: `cl-nagoya/ruri-v3-30m`（日本語特化）
- Rerankerモデル: `hotchpotch/japanese-reranker-xsmall-v2`
- Qdrant: `http://localhost:6333`
- サーバーポート: `26262`
- タイムゾーン: `Asia/Tokyo`

### 設計上の注意点

- サーバーは `stateless_http=True` で起動（セッション管理なし。全状態はSQLiteに保持）
- Personaごとに独立したSQLiteファイルとQdrantコレクションを持つ
- `tools/` 配下のファイル（`crud_tools.py`, `search_tools.py` 等）は `unified_tools.py` のハンドラーから内部的に呼ばれるが、直接MCPツールとして公開されていない
- Ebbinghaus忘却曲線ワーカーはバックグラウンドスレッドで動作し、`recall`時に `boost_on_recall()` で強度を上げる

### 外部MCPサーバー

Nous は以下の機能を外部MCPサーバーに委譲している。docker-compose.yml で一緒に起動する。

| サービス | MCPサーバー | 提供ツール（例） |
|----------|-------------|-----------------|
| **Playwright MCP** | `mcr.microsoft.com/playwright/mcp:latest` (port 8931) | `playwright__browser_navigate`, `playwright__browser_click`, `playwright__browser_snapshot`, `playwright__browser_fill`, `playwright__browser_evaluate` 等 20+ ツール |
| **OpenSandbox MCP** | `opensandbox-mcp-{persona}` (port 8001-8003) | `opensandbox__sandbox_create`, `opensandbox__sandbox_execute`, `opensandbox__sandbox_files`, `opensandbox__sandbox_install`, `opensandbox__sandbox_reset` 等 20 ツール |

**コード実行サンドボックス**は従来の Docker SDK 直接制御から **OpenSandbox** に移行した。OpenSandbox は Docker Compose 1ファイル完結、SQLite 内蔵、sandbox 単位のコンテナ分離を提供する。

**ペルソナ分離**: 単一 `opensandbox` サーバーに対して、persona ごとに独立した `opensandbox-mcp` インスタンスが接続する。各インスタンスは別プロセス・別 `ServerState` を持ち、persona 間で sandbox_id は共有されない。

```
opensandbox (port 8090)
  ├── opensandbox-mcp-herta (port 8001, 独立 ServerState)
  ├── opensandbox-mcp-alice (port 8002, 独立 ServerState)
  └── opensandbox-mcp-bob   (port 8003, 独立 ServerState)
```

各 persona の `ChatConfig.mcp_servers` には `http://opensandbox-mcp-{persona}:8000/mcp` が自動設定される。`docker-compose.yml` に `NOUS_PERSONAS` と同数のサービスを手動定義する。

**ブラウザ操作**は従来の `browser` ツールから **Playwright MCP** に移行した。Playwright MCP は headless Chromium で動作し、ナビゲーション・クリック・フォーム入力・スクリーンショット等を網羅する。

OpenCode 等の MCP クライアントから接続する場合の設定例:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "docker",
      "args": ["exec", "-i", "playwright", "node", "/app/cli.js"],
      "url": "http://localhost:8931"
    },
    "opensandbox": {
      "command": "docker",
      "args": ["exec", "-i", "opensandbox-mcp-herta", "opensandbox-mcp"],
      "url": "http://localhost:8001"
    }
  }
}
```

注意: `opensandbox-mcp-{persona}` のホストポートは persona ごとに異なる (`8001`=herta, `8002`=alice, `8003`=bob)。`docker-compose.yml` の定義に合わせて調整する。
