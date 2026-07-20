# コード実行サンドボックス

Nous のコード実行サンドボックスは **OpenSandbox** を利用する。
従来の `llm-sandbox[docker]`（Docker SDK 直接制御）およびカスタム `browser` ツールは廃止され、
OpenSandbox MCP + Playwright MCP に移行した。

---

## アーキテクチャ

```
ホストOS
│
├─ [opensandbox]         ← OpenSandbox Server（port 8090）
│   └─ Docker ソケット経由で sandbox コンテナを管理
│       ├─ sandbox_001  ── persona A 専用ワークスペース
│       ├─ sandbox_002  ── persona B 専用ワークスペース
│       └─ ...
│
├─ [opensandbox-mcp]    ← OpenSandbox MCP ゲートウェイ（port 8000）
│   └─ MCP プロトコルで sandbox 操作を提供（20 ツール）
│
└─ [playwright]         ← Playwright MCP（port 8931）
    └─ headless Chromium + 20+ ブラウザ操作ツール
```

### 従来構成からの変更点

| 項目 | 変更前 | 変更後 |
|------|--------|--------|
| コード実行 | `llm-sandbox[docker]` Docker SDK 直接制御 | OpenSandbox Server + MCP |
| ブラウザ操作 | カスタム `browser` ツール | Playwright MCP（外部） |
| ファイル操作 | `sandbox_files` ツール | OpenSandbox `sandbox_files` |
| ペルソナ分離 | バインドマウント `data/persona/{persona}/sandbox/` | OpenSandbox sandbox 単位のコンテナ分離 |

---

## セットアップ

### 1. Docker Compose（推奨）

`docker-compose.yml` に opensandbox / opensandbox-mcp / playwright サービスが定義されている。

```bash
docker-compose up -d
```

起動後、各サービスの状態を確認:

```bash
docker-compose ps
docker-compose logs opensandbox
docker-compose logs opensandbox-mcp
docker-compose logs playwright
```

### 2. 環境変数

OpenSandbox は `.env` の `DATA_ROOT` 配下にデータを永続化する。追加の環境変数は基本的に不要。

```env
# OpenSandbox のデータ永続化パス（docker-compose.yml で自動設定）
# ${DATA_ROOT}/opensandbox/volumes/
```

---

## OpenSandbox MCP ツール一覧

OpenSandbox MCP は以下のツールを提供する（計 20 ツール）:

| ツール | 説明 |
|--------|------|
| `sandbox_create` | 新しい sandbox を作成 |
| `sandbox_execute` | sandbox 内でコード実行 |
| `sandbox_files` | sandbox 内ファイル操作（list/read/write/append/delete） |
| `sandbox_install` | sandbox 内にパッケージインストール |
| `sandbox_reset` | sandbox リセット（files/packages/full） |
| `sandbox_list` | sandbox 一覧 |
| `sandbox_info` | sandbox 詳細情報 |
| 他 13 ツール | ファイルアップロード/ダウンロード等 |

**ツール命名規則**: MCP クライアントからは `opensandbox__sandbox_create` のように `opensandbox__` プレフィックスでアクセスする。

---

## Playwright MCP ツール一覧

Playwright MCP は以下のツールを提供する:

| ツール | 説明 |
|--------|------|
| `browser_navigate` | URL に移動 |
| `browser_click` | 要素をクリック |
| `browser_snapshot` | ページのアクセシビリティスナップショット取得 |
| `browser_fill` | フォームフィールドに入力 |
| `browser_evaluate` | JavaScript 実行 |
| `browser_screenshot` | スクリーンショット取得 |
| 他 15+ ツール | ページ操作全般 |

**ツール命名規則**: MCP クライアントからは `playwright__browser_navigate` のように `playwright__` プレフィックスでアクセスする。

---

## ペルソナ分離

OpenSandbox は **sandbox 単位のコンテナ分離** でペルソナ分離を実現する:

- ペルソナごとに独立した sandbox コンテナが作成される
- 各 sandbox は `cap_drop: ALL` + `no-new-privileges` で動作
- ファイルシステムは sandbox 内に隔離され、他のペルソナからアクセス不可
- OpenSandbox の設定（`docker-compose.yml` configs セクション）でセキュリティポリシーを一括管理

---

## セキュリティ

- **OpenSandbox**: Docker コンテナ単位の分離 + ケーパビリティ制限
- **Playwright MCP**: headless Chromium sandbox モード + 隔離ユーザーデータディレクトリ
- **ネットワーク**: 両サービスとも必要最小限のポートのみ公開
- **データ永続化**: `${DATA_ROOT}` 配下に保存され、コンテナ削除後も保持

---

## トラブルシューティング

### OpenSandbox が起動しない

```bash
docker-compose logs opensandbox
# Docker ソケットのマウントを確認
docker-compose exec opensandbox ls -la /var/run/docker.sock
```

### OpenSandbox MCP に接続できない

```bash
# opensandbox サービスのヘルスチェック
curl http://localhost:8090/health
# opensandbox-mcp のログ
docker-compose logs opensandbox-mcp
```

### Playwright MCP が応答しない

```bash
# ヘルスチェック
curl http://localhost:8931/health
# ログ確認
docker-compose logs playwright
```
