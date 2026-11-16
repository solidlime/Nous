# コード実行サンドボックス

ペルソナがホストと隔離されたコンテナの中でコードを動かすための構成。

旧 OpenSandbox 案（`opensandbox` / `opensandbox-mcp` / `playwright` の3サービス）は破棄した。
現行は **sandbox-manager 1サービス + 動的生成コンテナ**。git 履歴にだけ残っている。

---

## なぜ manager を挟むか

`docker.sock` を nous 本体に渡すと、nous が侵害された瞬間にホスト root まで届く。
manager に閉じれば、触れるのは sandbox の作成・exec・停止だけになる。

| 案 | 判断 |
|---|---|
| nous に sock | 却下。攻撃面が nous の全コードに広がる |
| ペルソナごとに compose サービス | 却下。ペルソナは DB で増減するので、作るたびに編集と再デプロイが要る |
| **manager にだけ sock、ペルソナは `docker run` で動的生成** | 採用 |

副次的に、アイドル停止のタイマーが nous の再起動で消えない。
`docker compose -p nous-sandbox ps` で sandbox だけを擬似スタックとして一望できる。

---

## 構成

```
docker compose（nous スタック）
├─ qdrant
├─ nous              ← sock 持たない。sandbox-manager に HTTP で頼む
└─ sandbox-manager   ← sock を持つのはこいつだけ（nous と同一イメージ・別プロセス）
     └─ docker run で <persona>-sandbox（動的生成）
```

コンテナ名は必ず `<persona>-sandbox`。素の `<persona>` はホストの他コンテナと衝突する。
`docker exec herta-sandbox bash` で直接入れる。

manager が付けるラベルで、sandbox は擬似 compose スタックとして扱える:

```
com.docker.compose.project=nous-sandbox
com.docker.compose.service=sbx-<persona>
com.nous.sandbox=1
```

`docker compose -p nous-sandbox ps` / `stop` が効く。
`com.nous.sandbox=1` は `/reset` の安全確認にも使う（このラベルの無いコンテナは消さない）。

---

## sandbox の中身

| コンテナ内 | ホスト | モード |
|---|---|---|
| `/home/<persona>/workspace` | `${DATA_ROOT}/persona/<persona>/workspace` | rw |
| `/home/<persona>/.agents/skills` | `${DATA_ROOT}/persona/<persona>/skills` | rw |
| `/home/<persona>/.agents/global-skills` | `${DATA_ROOT}/skills` | ro |

**渡さないもの**: memory（`memory.sqlite` / `inventory.sqlite` / `config.json`）、wiki。
記憶化は nous 側の自動抽出が担うので、sandbox に DB を持たせる必要がない。

スキルはグローバルとペルソナ専用の2本。同名はペルソナ優先（`/api/skills/{persona}` も同じ順で重ねる）。
sandbox 内のエージェントには AGENTS.md で両方のパスを教える。

**注意**: `${DATA_ROOT}/<persona>/` は使わない。既存の `persona_dir` 規約（`${DATA_ROOT}/persona/<persona>`）と二重になる。

---

## manager の API

`sandbox-manager` は `nous.services.sandbox_manager` を `python -m` で起動する FastAPI アプリ。
ポート 8080、compose ネットワーク内にだけ公開する。

| メソッド | パス | 役割 |
|---|---|---|
| POST | `/exec` | `{persona, command, cwd?, timeout_seconds?, image?, network?, memory?, idle_minutes?}` → `{status, exit_code, stdout_tail, stderr_tail, truncated, log_path}` |
| POST | `/reset` | `{persona, image?, network?, memory?, idle_minutes?}` → コンテナ削除 + `${DATA_ROOT}/persona/<p>/workspace` 削除して作り直す。exec の実行中は拒否する（拒否判定と `rmtree` の間に exec が始まる狭い窓は残る）。workspace を消せない・作れないときは `status="error"` |
| GET | `/list` | 稼働中 sandbox の一覧 |
| POST | `/touch` | 最終利用時刻の更新（今は nous 側に呼び出し元がない） |
| GET | `/health` | 死活確認 |

- persona は `[a-z0-9_-]` のみ。外れたら 400
- exec は `docker exec [-w cwd] <persona>-sandbox bash -lc <command>`。subprocess は `shell=False` のリスト引数で、`command` 文字列は内側の `bash -lc` にだけ渡す
- 出力は末尾 120 行だけ返し、全文は `{DATA_ROOT}/sandbox/<persona>/logs/` に落とす（`log_path`）
- アイドル `sandbox_idle_minutes`（既定 30）で `docker stop`。状態は残し、次の exec で `docker start` する

---

## nous 側

ツール名は `sandbox`。`sandbox_enabled` と `sandbox_manager_url` の両方が揃ったときだけ公開する
（`workspace_root` の有無とは無関係）。既定は無効なので、使うペルソナで明示的に有効化する。
`bash` / `write_file` / `edit_file` と同じく承認が要る（`shell_approval_mode` に従う）。

| 設定 | 既定 | 意味 |
|---|---|---|
| `sandbox_enabled` | `false` | サンドボックスツールのマスタースイッチ |
| `sandbox_manager_url` | `""` | manager の URL。空なら enabled でもツールを出さない |
| `sandbox_image` | （空） | 生成するコンテナのイメージ。空なら manager の `SANDBOX_IMAGE`。素の ubuntu なので python も入っていない |
| `sandbox_network` | （空） | sandbox のネットワーク。空なら manager の `SANDBOX_NETWORK`。**compose ネットワークを指定しないこと** |
| `sandbox_memory` | （空） | メモリ上限。空なら manager の `SANDBOX_MEMORY` |
| `sandbox_idle_minutes` | `0` | 停止までのアイドル時間。0 なら manager の `SANDBOX_IDLE_MINUTES` |

manager に届かない・未設定のときは `status="error"` を返す。例外は投げない。

戻り値は manager の `stdout_tail` / `stderr_tail` をそのまま返す（`bash` ツールの
`stdout` とは別名。manager の契約を優先している）。

### manager 側の環境変数（compose で渡す）

| 変数 | 既定 | 意味 |
|---|---|---|
| `NOUS_DATA_ROOT` | `/data` | manager コンテナ内のデータ根。ログと workspace 削除に使う |
| `SANDBOX_HOST_DATA_ROOT` | （inspect で自動） | bind mount の source。**ホスト絶対パス**で渡す。inspect の結果と違えば拒否する |
| `SANDBOX_MANAGER_HOST` | `0.0.0.0` | uvicorn の bind。ホストで直接動かすなら `127.0.0.1` |
| `SANDBOX_IMAGE` | `ubuntu:24.04` | 上の `sandbox_image` の既定 |
| `SANDBOX_NETWORK` | `bridge` | 上の `sandbox_network` の既定 |
| `SANDBOX_MEMORY` | `4g` | 上の `sandbox_memory` の既定 |
| `SANDBOX_IDLE_MINUTES` | `30` | 上の `sandbox_idle_minutes` の既定 |

`SANDBOX_HOST_DATA_ROOT` が相対パスだと docker は source を名前付きボリュームとして扱うので、
設定するなら絶対パスにする。未設定なら manager が自分の `/data` のマウント元を `docker inspect` で調べる
（`{{.Id}}` は 64 桁 hex。先頭 12 文字の `HOSTNAME` と突き合わせ、一致しなければ adopt しない）。
**どちらも解決できないときは bind mount を作らず `status="error"`**（ホスト直下に `/data` を
作って空の sandbox を動かす事故を防ぐ）。

---

## セキュリティ

- sock を持つのは `sandbox-manager` だけ。nous は持たない
- **`SANDBOX_NETWORK` に compose ネットワークを指定しない**。指定すると、1つの sandbox から他の sandbox の manager API（無認証）に届き、他人の sandbox を exec / rm できてしまう
- sandbox は `no-new-privileges` + `--pids-limit 1024` + メモリ・CPU 上限付き。manager は `cap_drop: ALL`
- ホストのマウントは workspace とスキルだけ。memory / wiki / config は渡さない
- exec の引数は `shell=False`。コマンド文字列はコンテナ内の `bash -lc` でのみ解釈する
- コンテナは `com.nous.sandbox=1` ラベルで識別する。名前だけ一致する他人のコンテナは exec / rm しない

**manager は無認証**。`/exec` は任意コマンド実行、`/reset` は workspace 削除なので、
ネットワーク分離（`SANDBOX_NETWORK` に compose ネットワークを置かない）が唯一の防壁。
共有トークンは未実装。

---

## 保留

- 長いコマンドのストリーミングは入れない（末尾 N 行だけ返す）。必要になったら SSE
- 外側の `subprocess` がタイムアウトしても、コンテナ内のプロセスは残る（孤児）
- sock のパーミッション（manager を root 以外で動かすなら `group_add`）は実機確認
- sandbox の `--user`（uid 不一致で書けない問題）は未対応

---

## トラブルシューティング

```bash
# manager の状態
docker compose ps sandbox-manager
docker compose logs -f sandbox-manager

# sandbox の一覧（manager 経由）
curl -s http://sandbox-manager:8080/list

# 擬似スタックとして見る
docker compose -p nous-sandbox ps

# 中に入る
docker exec -it <persona>-sandbox bash
```
