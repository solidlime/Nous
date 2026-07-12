# Nous

> AI に永続記憶を。ペルソナを持った対話を。

[![CI](https://github.com/solidlime/Nous/actions/workflows/ci.yml/badge.svg)](https://github.com/solidlime/Nous/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)

**Nous** は [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 対応の永続記憶サーバーです。Claude Desktop や OpenCode につなぐだけで、あなたの AI が「覚える」「思い出す」「検索する」能力を手に入れます。

---

## できること

| 機能 | 説明 |
|------|------|
| 🔍 **ハイブリッド検索** | 意味検索（semantic）+ キーワード検索。ほしい記憶にすぐたどり着ける |
| 🧠 **忘却曲線** | Ebbinghaus の忘却曲線で、よく使う記憶は強く、使わない記憶は自然に薄れる |
| 👤 **ペルソナ分離** | 複数の人格・ユーザーを完全に分けて管理。Bearer トークンで簡単に切り替え |
| 🌐 **Web ダッシュボード** | ブラウザから記憶の確認・編集・チャットができる |
| 💬 **チャット機能** | WebUI でペルソナとリアルタイム会話。SSE ストリーミングで快適 |
| 🎯 **目標・約束の管理** | Goal / Promise のライフサイクルを追跡。達成状況を常に把握 |
| 📦 **アイテム・装備** | 所持品と装備を管理。記憶作成時の装備状態を自動記録 |
| 🏃 **コード実行サンドボックス** | Docker 分離環境で Python/Bash を安全に実行 |
| 💡 **Reflection & Mental Model** | LLM による高次洞察とパターン抽象化を自動実行 |
| 🔗 **エンティティグラフ** | 人物・場所・概念の関係性を知識グラフで可視化 |
| 🌡️ **Dynamic Temperature** | 感情駆動の温度調整で自然な会話バリエーションを実現 |
| 🎨 **Persona Portrait** | AIによるペルソナ画像生成（ComfyUI対応・デフォルトOFF） |
| 📝 **Author's Note** | システムプロンプトへの永続コンテキスト注入でロールの一貫性を維持 |
| 🎤 **Voice (Irodori-TTS)** | 日本語TTS音声出力（オプション・GPUサーバー必須・デフォルトOFF） |
| 🃏 **SillyTavern Card Export** | PNGメタデータ埋め込みのペルソナカードエクスポート (`/api/personas/{persona}/card.png`) |
| ⚡ **リアルタイム感情SSE** | 感情・体調の変化をSSEでリアルタイム通知。WebUIが即時反映 |

---

## クイックスタート

```bash
git clone https://github.com/solidlime/Nous.git
cd Nous
docker-compose up -d
```

起動したら **http://localhost:26262** をブラウザで開くだけ。

---

## LLM と接続する

### Claude Desktop

`claude_desktop_config.json` に以下を追加:

```json
{
  "mcpServers": {
    "nous": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:26262/mcp"],
      "env": {
        "MCP_REMOTE_HEADER_X-Persona": "your_name"
      }
    }
  }
}
```

### OpenCode

```json
{
  "mcpServers": {
    "nous": {
      "url": "http://localhost:26262/mcp",
      "headers": {
        "X-Persona": "your_name"
      }
    }
  }
}
```

### VS Code (GitHub Copilot)

```json
{
  "mcpServers": {
    "nous": {
      "url": "http://localhost:26262/mcp",
      "headers": {
        "Authorization": "Bearer your_name"
      }
    }
  }
}
```

> **Persona の指定方法**: 優先順位は `Bearer トークン` > `X-Persona ヘッダー` > 環境変数 `PERSONA` > デフォルト `"default"`。詳しくは [Claude Desktop セットアップ](docs/claude_desktop_setup.md) を参照。

---

## MCP ツール一覧

接続すると、LLM から以下のツールが使えるようになります。

| ツール | できること |
|--------|-----------|
| `get_context()` | ペルソナの状態・最近の記憶・感情・装備を一括取得（セッション開始時に呼ぶ） |
| `memory_create(content, ...)` | 新しい記憶を作成 |
| `memory_read(memory_key?, limit?)` | 記憶を読み取る |
| `memory_update(memory_key, ...)` | 記憶を更新 |
| `memory_delete(memory_key \| query)` | 記憶を削除 |
| `memory_search(query, ...)` | ハイブリッド検索（semantic + keyword + smart） |
| `memory_stats(top_n?)` | 記憶の統計情報 |
| `update_context(emotion?, ...)` | 感情・身体状態・ユーザー情報を更新 |
| `goal_manage(operation, ...)` | 目標の作成・達成・取消 |
| `item_add / equip / search` | アイテムと装備の管理（3ツール） |
| `sandbox(code, language?)` | コード実行（Docker サンドボックス） |
| `sandbox_files(operation, path?)` | サンドボックス内のファイル操作 |
| `invoke_skill(name, task)` | スキルを呼び出して LLM の能力を拡張 |

使い方の詳細は [LLM 利用ガイド](docs/llm_usage_guide.md) を参照。

---

## WebUI

`http://localhost:26262` にアクセスすると、以下の画面が使えます:

| 画面 | できること |
|------|-----------|
| **ダッシュボード** | 記憶の統計・タグ分布・日次推移を表示 |
| **チャット** | ペルソナとリアルタイム会話（SSE ストリーミング） |
| **記憶管理** | 記憶の一覧表示・編集・削除 |
| **知識グラフ** | エンティティ間の関係性を可視化 |
| **設定** | チャット設定・LLM プロバイダー・API キーなどをブラウザから変更 |
| **サンドボックス** | コード実行環境の管理 |
| **アクティビティ** | 操作履歴のタイムライン表示 |
| **スキル管理** | 利用可能なスキルの確認と有効/無効の切り替え |

---

## 設定

主要な環境変数。ネストした設定は `__`（アンダースコア2つ）区切りで指定します。

| 環境変数 | デフォルト | 説明 |
|----------|-----------|------|
| `NOUS_DATA_ROOT` | `./data` | 全データの保存先 |
| `NOUS_SERVER__PORT` | `26262` | HTTP ポート |
| `NOUS_SERVER__HOST` | `0.0.0.0` | バインドアドレス |
| `NOUS_QDRANT__URL` | `http://localhost:6333` | Qdrant 接続先 |
| `NOUS_EMBEDDING__MODEL` | `cl-nagoya/ruri-v3-30m` | 埋め込みモデル（日本語特化） |
| `NOUS_DEFAULT_PERSONA` | `default` | デフォルト Persona 名 |
| `NOUS_TIMEZONE` | `Asia/Tokyo` | タイムゾーン |
| `NOUS_SANDBOX__ENABLED` | `true` | コード実行サンドボックス |
| `NOUS_MEMORY_ENRICHMENT__ENABLED` | `true` | 記憶作成時の LLM 自動補完 |
| `NOUS_FORGETTING__ENABLED` | `true` | Ebbinghaus 忘却曲線 |

全設定項目は WebUI の**設定画面**から確認・変更できます（WebUI からの変更は `docker-compose.yml` の環境変数より優先されます）。



---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [Claude Desktop セットアップ](docs/claude_desktop_setup.md) | mcp-remote / mcp-proxy を使った接続手順 |
| [LLM 利用ガイド](docs/llm_usage_guide.md) | LLM がツールを使う際のベストプラクティス |
| [サンドボックス](docs/sandbox.md) | Docker コード実行の設定とアーキテクチャ |
| [HTTP API リファレンス](docs/http_api_reference.md) | REST API の詳細 |
| [記憶機能](docs/memory_features.md) | 忘却曲線・検索・エンリッチメントの詳細 |

---

## 技術スタック

| カテゴリ | 技術 |
|----------|------|
| 言語 | Python 3.12+ |
| MCP フレームワーク | FastMCP |
| データベース | SQLite（WAL モード） |
| ベクトルストア | Qdrant |
| 埋め込みモデル | cl-nagoya/ruri-v3-30m（日本語特化） |
| Reranker | hotchpotch/japanese-reranker-xsmall-v2 |
| 設定管理 | Pydantic v2 |
| ロギング | structlog |
| コンテナ | Docker / Docker Compose |

---

## ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照。

---

**Nous** — Built by [solidlime](https://github.com/solidlime)
