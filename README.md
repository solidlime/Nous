# Nous

> AI に永続記憶を。ペルソナを持った対話を。

[![CI](https://github.com/solidlime/Nous/actions/workflows/ci.yml/badge.svg)](https://github.com/solidlime/Nous/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)

**Nous** は [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 対応の永続記憶サーバーです。Claude Desktop や OpenCode につなぐだけで、あなたの AI が「覚える」「思い出す」「検索する」能力を手に入れます。

---

## できること

### 🧠 記憶システム
- **ハイブリッド検索**: 意味検索 + キーワード検索で、ほしい記憶にすぐたどり着ける
- **忘却曲線**: よく使う記憶は強く、使わない記憶は自然に薄れる（Ebbinghaus モデル）
- **自動記録**: 会話中の重要情報を自動で記憶に保存

### 👤 ペルソナ管理
- **複数ペルソナ**: 複数の人格・ユーザーを完全に分けて管理
- **感情・体調**: ペルソナの感情状態や体調を追跡・減衰
- **アイテム・装備**: 所持品と装備を管理。記憶作成時の装備状態を自動記録
- **目標・約束**: Goal / Promise のライフサイクルを追跡

### 💬 WebUI ダッシュボード
- **リアルタイムチャット**: SSE ストリーミングで快適な会話
- **記憶管理**: 記憶の一覧表示・編集・削除・検索
- **知識グラフ**: エンティティ間の関係性を可視化
- **設定画面**: ブラウザから全ての設定を変更可能

### 🎨 オプション機能
- **画像生成**: ComfyUI 連携でペルソナの画像を自動生成（デフォルト OFF）
- **音声合成**: Irodori TTS による日本語音声出力（デフォルト OFF）
- **コード実行**: Docker サンドボックスで Python/Bash を安全に実行

#### ComfyUI 保存ワークフローの直接実行

`image_gen_comfyui_workflow_source` を `"comfyui"` に設定すると、
ComfyUI 側の `user/default/workflows/` に保存済みのワークフローを
`/userdata` API で取得し、`/object_info` を併用して API 形式に変換して実行する。
Nous サーバー側にワークフローファイルを置く必要はない。

- `image_gen_comfyui_workflow_source`: `"local"`（既定・従来動作）| `"comfyui"`
- `image_gen_comfyui_workflow_name`: ComfyUI 側のワークフローファイル名（例: `"Anima_T2I_Turbo_Aesthetic.json"`）

変換時に UI ノードのタイトルが API 形式の `_meta.title` に写るため、
ノードタイトルに `NOUS:prompt` / `NOUS:negative_prompt` / `NOUS:reference_image` /
`NOUS:width` / `NOUS:height` / `NOUS:seed` / `NOUS:display` のタグを付ければ値の
注入が機能する。シードは毎回ランダム化され、`EmptyLatentImage` の width / height /
batch_size は実行時に上書きされる（`apply_generation_params`）。

モデル・LoRA・steps・cfg・sampler・scheduler・denoise はワークフロー側に埋め込む
（旧 `NOUS:checkpoint` / `NOUS:lora` / `NOUS:steps` / `NOUS:cfg` / `NOUS:sampler` /
`NOUS:scheduler` / `NOUS:denoise` タグと `image_gen_comfyui_checkpoint` 等の設定は廃止）。

対応外（現時点）: サブグラフ / V3 dynamic combo / GetNode-SetNode / bypass パススルー
を含むワークフロー。必要なら comfy-cli の変換器を移植する。

---

## クイックスタート

```bash
git clone https://github.com/solidlime/Nous.git
cd Nous
docker compose up -d
```

起動したら **http://localhost:26262** をブラウザで開くだけ。

### 環境変数（`.env`）

```bash
# 必須: いずれか1つの LLM API キー
NOUS_ANTHROPIC_API_KEY=your_key
# NOUS_OPENAI_API_KEY=your_key
# NOUS_OPENROUTER_API_KEY=your_key

# オプション
TZ=Asia/Tokyo
DATA_ROOT=./data
```

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

> **Persona の指定方法**: 優先順位は `Bearer トークン` > `X-Persona ヘッダー` > 環境変数 `PERSONA` > デフォルト `"default"`。

---

## WebUI

`http://localhost:26262` にアクセスすると、以下の画面が使えます:

| 画面 | できること |
|------|-----------|
| **チャット** | ペルソナとリアルタイム会話（SSE ストリーミング） |
| **オーバービュー** | 記憶の統計・タグ分布・日次推移を表示 |
| **記憶管理** | 記憶の一覧表示・編集・削除 |
| **知識グラフ** | エンティティ間の関係性を可視化 |
| **設定** | チャット設定・LLM プロバイダー・API キーなどをブラウザから変更 |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [Claude Desktop セットアップ](docs/claude_desktop_setup.md) | mcp-remote / mcp-proxy を使った接続手順 |
| [LLM 利用ガイド](docs/llm_usage_guide.md) | LLM がツールを使う際のベストプラクティス |
| [アーキテクチャ](docs/architecture.md) | 技術スタック・ディレクトリ構造・設計パターン |
| [HTTP API リファレンス](docs/http_api_reference.md) | REST API の詳細 |
| [記憶機能](docs/memory_features.md) | 忘却曲線・検索・エンリッチメントの詳細 |
| [サンドボックス](docs/sandbox.md) | Docker コード実行の設定とアーキテクチャ |

---

## ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照。

---

**Nous** — Built by [solidlime](https://github.com/solidlime)
