# コード実行サンドボックス

Nous のチャットでは `llm-sandbox[docker]` を使った Python コード実行サンドボックスを利用できます。
コードはコンテナ内の IPython カーネルで実行され、結果がチャットに返ってきます。

---

## アーキテクチャ

```
ホストOS
│
├─ [nous]
│   /var/run/docker.sock → ホストDockerソケット（直接マウント）
│   └─ Python/IPython サンドボックスコンテナを spawn（動的生成）
│       /sandbox → /data/memory/{persona}/sandbox/ (bind mount)
│       cap_drop: ALL + no-new-privileges（ハードニング済み）
│
└─ [sandbox]  ← 永続化用コンテナ（DooD補助）
    /home/{persona}/ → ${DATA_ROOT}/sandbox/{persona}/
    cap_drop: ALL + DAC_OVERRIDE + CHOWN + FOWNER + SETUID + SETGID
```

- **ファイル永続化**: コンテナの `/sandbox` は `data/memory/{persona}/sandbox/` にバインドマウントされます。Nous を再起動してもファイルは残ります。
- **ペルソナ分離**: ペルソナごとに独立したワークスペースを持ちます。
- **セキュリティ**: IPython コンテナは `cap_drop: ALL` + `no-new-privileges` で動作し、`/sandbox` 以外にアクセスできません。

---

## セットアップ

### 1. Docker Compose（推奨）

`docker-compose.yml` には `nous` サービスにホストDockerソケット（`/var/run/docker.sock`）がマウントされており、サンドボックスコンテナを sibling コンテナとして起動します（DooD: Docker-outside-of-Docker）。

```bash
docker-compose up -d
```

起動後、WebUI のチャット設定で **コード実行を許可** をオンにするか、`.env` に以下を追記します。

```env
NOUS_SANDBOX__ENABLED=true
# DOCKER_HOST は空のままでOK — 自動検出されます
NOUS_SANDBOX__DOCKER_HOST=
```

その後コンテナを再起動します。

```bash
docker-compose restart nous
```

### 2. ローカル Python（サーバーを直接起動する場合）

Docker Desktop（または Docker Engine）が起動している状態で実行します。

```bash
NOUS_SANDBOX__ENABLED=true python -m nous.main
```

この場合、ローカルの Docker ソケット（`/var/run/docker.sock` 等）が自動検出されます。

### 3. リモート Docker ホスト

別のホストで Docker デーモンを公開している場合（開発・テスト用）:

```env
NOUS_SANDBOX__ENABLED=true
NOUS_SANDBOX__DOCKER_HOST=tcp://192.168.1.100:2375
```

TLS を有効にしたリモート Docker（本番推奨）:

```env
NOUS_SANDBOX__DOCKER_HOST=tcp://192.168.1.100:2376
# Docker Python SDK は DOCKER_TLS_VERIFY / DOCKER_CERT_PATH 環境変数も参照します
DOCKER_TLS_VERIFY=1
DOCKER_CERT_PATH=/path/to/certs
```

---

## WebUI からの設定

チャット設定パネルの **🔬 コード実行サンドボックス** セクションで設定できます。

| フィールド | 説明 |
|-----------|------|
| コード実行を許可 | サンドボックスを ON/OFF する |
| Docker Host | 空 = グローバル設定（`NOUS_SANDBOX__DOCKER_HOST`）に従う。`tcp://host:2375` を指定するとこのペルソナだけリモートに接続する |

ペルソナごとに異なる Docker Host を設定できます。

---

## ファイル永続化

サンドボックス内の `/sandbox` は以下のホストパスにバインドマウントされます。

```
data/memory/{persona}/sandbox/
```

- `docker-compose` 環境では `./data/sandbox/` として永続化されます。
- ファイルマネージャー（WebUI の 📁 タブ）からアップロード・ダウンロード・削除が可能です。

---

## セキュリティ上の注意

- **DooD**（Docker-outside-of-Docker）: `nous` コンテナが `/var/run/docker.sock` を介してホストDockerデーモンにアクセスし、サンドボックスコンテナを sibling コンテナとして起動します。分離された DinD デーモンは不要です。
- **サンドボックスコンテナ**（ユーザーコードが実行される場所）は `cap_drop: ALL` + `no-new-privileges` + `/sandbox` のみのマウントで動作します。
- **リモート Docker** を公開する場合は必ず TLS クライアント認証を設定してください。
- サンドボックスコンテナはデフォルトでインターネットアクセスが可能です。必要に応じて Docker のネットワーク設定で制限してください。

---

## トラブルシューティング

### `Failed to start sandbox: ...` / Docker に接続できない

- Docker ソケットが nous コンテナにマウントされているか確認: `docker-compose exec nous ls -la /var/run/docker.sock`
- ホストの Docker が起動しているか確認: `docker info`
- docker-compose のログ: `docker-compose logs nous`
- `NOUS_SANDBOX__ENABLED=true` が設定されているか確認

### リモートホストに接続できない

- `NOUS_SANDBOX__DOCKER_HOST` の値が正しいか確認
- ファイアウォールでポート 2375/2376 が開放されているか確認
- TLS 設定を使っている場合は証明書パスが正しいか確認

### ファイルが `/sandbox` に残らない

- サンドボックスが初回起動中はディレクトリ作成に少し時間がかかります
- `data/memory/{persona}/sandbox/` がホスト側に存在するか確認してください

