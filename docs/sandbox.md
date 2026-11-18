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

```text
docker compose（nous スタック）
├─ qdrant
├─ nous              ← sock 持たない。sandbox-manager に HTTP で頼む
└─ sandbox-manager   ← sock を持つのはこいつだけ（nous と同一イメージ・別プロセス）
     └─ docker run で <persona>-sandbox（動的生成）
```

コンテナ名は必ず `<persona>-sandbox`。素の `<persona>` はホストの他コンテナと衝突する。
`docker exec herta-sandbox bash` で直接入れる。

manager が付けるラベルで、sandbox は擬似 compose スタックとして扱える:

```text
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
| `/home/agent/workspace` | `${DATA_ROOT}/persona/<persona>/workspace` | rw |
| `/home/agent/wiki` | `${DATA_ROOT}/persona/<persona>/wiki` | rw |
| `/home/agent/uploads` | `${DATA_ROOT}/persona/<persona>/uploads` | rw |
| `/home/agent/media` | `${DATA_ROOT}/persona/<persona>/media` | ro |
| `/home/agent/.agents/skills` | `${DATA_ROOT}/persona/<persona>/skills` | rw |
| `/home/agent/.agents/global-skills` | `${DATA_ROOT}/skills` | ro |

**渡さないもの**: `db/`（`memory.sqlite` / `inventory.sqlite`）と `config.json`。
記憶化は nous 側の自動抽出が担うので、sandbox に DB を持たせる必要がない。

`media` は nous が書く生成物（画像・音声・アバター）なので ro。ペルソナが
ファイルを読む経路は sandbox に寄せる方針で、wiki / uploads はそこから書ける。

環境変数 `HOME=/home/agent` を固定し、uid/gid は `SANDBOX_UID` / `SANDBOX_GID`（既定 1026:100）。
manager は root で動くので、mkdir したマウント先は 777 にして書けるようにしてある
（`cap_drop: ALL` で chown できないため）。

**`$HOME` はイメージ側の罠で root 所有になりやすい。** Dockerfile の `WORKDIR /home/agent` が
`useradd -m` より先に走るので、`-m` は「ディレクトリが既にある」と判断して何もしない。
結果 `/home/agent` が `root:root 0755` のままだと、`pip install --user` や
`git config --global` が Permission denied になる（マウント先は 777 なので
「ワークスペースは書けるのに $HOME だけ書けない」という分かりにくい壊れ方をする）。
対策は2段:

1. イメージで `mkdir -p /home/agent/.agents && chown -R ${SANDBOX_UID}:${SANDBOX_GID} /home/agent`
2. manager が `ensure` 時に `docker exec -u 0 chown <uid>:<gid> /home/agent /home/agent/.agents`
   （既に作られたコンテナをイメージ再ビルドなしで直す。冪等なのでコンテナごとに1回だけ打つ。
   uid は `SANDBOX_UID` ではなく `docker inspect` の `.Config.User` を使う — 後から env を
   変えたときに、動いていない uid へ chown して $HOME を壊さないため）

`exec -u 0` は sandbox 側に既定の caps（`CAP_CHOWN`）が残っていることが前提。
**sandbox に `--cap-drop ALL` を入れるとこの修正は静かに無効になる**（`--cap-drop` を
入れていないことをテストで固定してある）。rootless では効かないが、元の症状が残るだけで
新しい壊れ方はしない（`logger.warning` が1回出る）。

nous（root）がマウント内に書くファイルも、置いた後に `chmod 0666`
（wiki ページ・ユーザー添付・exec の全文ログ）にしている。root 0644 のままだと
ペルソナの `edit_file` が Permission denied になる。

wiki の履歴（`wiki/_history/*.jsonl`）だけは 0644／dir 0755 のまま。dir に write が
あるとファイル mode に関係なく差し替えられるので、**dir 権限が履歴を守る唯一の防壁**で
ある。ここが 0777 になると版を偽造できる。内容の正しさ（改竄検知）は保証しない——
版を戻せることと、内容が正しいことは別。

置き換えは `nous/infrastructure/wiki/store.py` の `write_shared()` を通す（履歴と
gist 退避もこれ経由）。`mkstemp` で tmp を選び、`fchmod` してから `os.replace` する。
`.{name}.tmp` のような予測可能な名前だと、wiki を書けるペルソナが先に symlink を置いて、
nous（root）に他ペルソナの DB を truncate させられる。同じ理由で `write_shared()` は
親 dir の symlink を拒否し、`_path_for()` は
symlink のページを拒否し、`list_slugs()` も symlink を辿らない。

スキルはグローバルとペルソナ専用の2本。同名はペルソナ優先（`/api/skills/{persona}` も同じ順で重ねる）。
sandbox 内のエージェントには AGENTS.md で両方のパスを教える。

**注意**: `${DATA_ROOT}/<persona>/` は使わない。既存の `persona_dir` 規約（`${DATA_ROOT}/persona/<persona>`）と二重になる。

### ペルソナごとのレイアウト

```text
persona/<p>/
├─ config.json     ペルソナ設定
├─ db/             memory.sqlite / inventory.sqlite（WAL/SHM も同居）
├─ media/          images / tts_cache / avatar（nous が書く生成物）
├─ wiki/
├─ uploads/        ユーザーが投入したファイル
├─ skills/
├─ workspace/      ペルソナの作業場
└─ _legacy/        旧レイアウトの残骸（起動時に隔離される。消さない）
```

旧レイアウト（`memory.sqlite` 直下、`images/`、`tts_cache/`、`avatar/`、`${DATA_ROOT}/uploads/<p>`）は
起動時に `nous/infrastructure/persona_layout.py` が新レイアウトへ移す。新旧両方に
同名ファイルがあるときは上書きしない（片方のデータが消えるため）。

残骸の扱いは次のとおり。**自動では何も消さない。**

| 旧ファイル | 行き先 | 理由 |
|---|---|---|
| `<p>.db`（例 `herta.db`）＋ `-wal`/`-shm` | `db/memory.sqlite` | アプリが開くのは `db/memory.sqlite` なので、置き場所を変えるだけでは読まれない。`db/memory.sqlite` が既にある場合は触らず残す |
| `config.json.bak-*` | `_legacy/` | 移行前の控え。sandbox にも見せる必要が無い |
| `wiki_cleanup_*.json` | `_legacy/` | 一回限りのレポート |

移行状態の点検は `python scripts/check_persona_layout.py [data_root]`（読み取りのみ）。

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
- 出力は末尾 120 行だけ返し、全文はワークスペース内の `.nous/logs/` に落とす。`log_path` は**コンテナ視点のパス**（`/home/agent/workspace/.nous/logs/<ts>.log`）で返すので、モデルはそのまま `read_file` で読み直せる。ワークスペース外に置くと `resolve_in_workspace` に弾かれて `log_path` が空約束になる
- アイドル `sandbox_idle_minutes`（既定 30）で `docker stop`。状態は残し、次の exec で `docker start` する

---

## nous 側

ツール名は `sandbox` ではなく、ワークスペースツール（`bash` / `read_file` / `write_file` / `edit_file`）
そのものが sandbox 内で動く。`sandbox_enabled` と `sandbox_manager_url` の両方が揃ったときだけ
sandbox 既定になり（`workspace_root` は要らない）、別ツール `sandbox` は一覧に出さない。
使えないときは従来通り `workspace_root` 配下でローカル実行する。
`bash` / `write_file` / `edit_file` と同じく承認が要る（`shell_approval_mode` に従う）。

実装は `nous/application/chat/tools/sandbox_shell.py`。manager の `/exec` だけを使う
（`read_file` は `base64 -w0` をデコード、`write_file` は本文を base64 にして流し込む。
`edit_file` は読んで nous 側で exact-match 置換してから書き戻すので、コンテナに python/perl は要らない）。
パスは相対なら `/home/<persona>/workspace` 起点。コマンドもパス（`..` を含む）も制限しない。

| 設定 | 既定 | 意味 |
|---|---|---|
| `sandbox_enabled` | `false` | sandbox を既定のシェルにするスイッチ |
| `sandbox_manager_url` | `""` | manager の URL。空なら enabled でもローカル実行のまま |
| `sandbox_image` | （空） | 生成するコンテナのイメージ。空なら manager の `SANDBOX_IMAGE`（既定 `ghcr.io/solidlime/nous-sandbox:latest` = `docker/sandbox/Dockerfile`） |
| `sandbox_network` | （空） | sandbox のネットワーク。空なら manager の `SANDBOX_NETWORK`（既定 `nous-net`）。Docker 埋め込み DNS で `nous` を引くために user-defined network に載せている。manager の API にも届くので、トークン管理は前提 |
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
| `SANDBOX_IMAGE` | `ghcr.io/solidlime/nous-sandbox:latest` | 上の `sandbox_image` の既定。`docker/sandbox/Dockerfile` のビルド（python3 + venv / git / curl / 診断系一式） |
| `SANDBOX_NETWORK` | `nous-net` | 上の `sandbox_network` の既定 |
| `SANDBOX_ALLOWED_NETWORKS` | （空） | 許すネットワークの追加分（カンマ区切り）。既定で `none` と `bridge` だけ。compose は `nous-net` を足している |
| `SANDBOX_TZ` | 親の `TZ`（無ければ `UTC`） | sandbox に渡す `TZ`。compose は `TZ: ${TZ:-Asia/Tokyo}` を manager 自体に渡している |
| `SANDBOX_DNS_CHECK` | `1` | `1` なら起動後に `getent hosts nous` を叩き、失敗したら `status="error"`。`0` で skip |
| `SANDBOX_APT_EXTRA` | （空） | 起動時に差分インストールする apt パッケージ（カンマ区切り）。`dpkg -s` で不足分だけ `apt-get install`。失敗しても警告だけで run は通す |
| `SANDBOX_GIT_USER_NAME` / `SANDBOX_GIT_USER_EMAIL` | （空） | 空ならイメージの `git config --system`（persona / <persona@nous.local>）。設定すると `GIT_AUTHOR_*` / `GIT_COMMITTER_*` で上書きする |
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
- sandbox は `nous-net` に載る（`getent hosts nous` が通るため）。**そのぶん manager の API にも届く**ので、`NOUS_SANDBOX_MANAGER_TOKEN` は sandbox に渡さない・ログに出さない。分離を優先するなら `SANDBOX_NETWORK=bridge` + `SANDBOX_DNS_CHECK=0` に戻す（名前解決は諦める）
- sandbox は `no-new-privileges` + `--pids-limit 1024` + メモリ・CPU 上限付き。manager は `cap_drop: ALL`
- ホストのマウントは workspace とスキルだけ。memory / wiki / config は渡さない
- exec の引数は `shell=False`。コマンド文字列はコンテナ内の `bash -lc` でのみ解釈する
- コンテナは `com.nous.sandbox=1` ラベルで識別する。名前だけ一致する他人のコンテナは exec / rm しない

**manager は共有トークン必須**。`/health` を除く全 API が `X-Sandbox-Token` を要求する。
`NOUS_SANDBOX_MANAGER_TOKEN` が未設定なら 503、不一致は 401。nous は config.json の
`sandbox_manager_token` を送り、空ならツールが `status="error"` を返す（fail closed）。
sandbox は名前解決のために `nous-net` に載る。分離を優先する環境では `SANDBOX_NETWORK=bridge` と
`SANDBOX_DNS_CHECK=0` に戻す（DNS は引けなくなる）。

---

## 保留

- 長いコマンドのストリーミングは入れない（末尾 N 行だけ返す）。必要になったら SSE
- `timeout(1)` をコンテナ内で噛ませるので、打ち切りは exit 124（`-k 5` で SIGKILL まで5秒）。外側の `subprocess` が先に切れた場合だけ、コンテナ内のプロセスが残りうる
- manager を再起動すると、稼働中の sandbox は `RESTART_GRACE_SECONDS`（300秒）後に idle 判定に入る
- sock のパーミッション（manager を root 以外で動かすなら `group_add`）は実機確認
- 既知の穴（残り）: nous がマウント内の**任意の場所**に書いたファイルの所有者は root のまま。
  wiki / uploads / ログは `chmod 0666` で対処済みだが、新しい書き込み経路を足すときは同じ対処が要る

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
