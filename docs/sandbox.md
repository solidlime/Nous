# ペルソナ専用マシン（sandbox）

ペルソナに貸し切る 1 台の Linux マシンとして sandbox を動かす。隔離された使い捨てコンテナではなく、
**root で動き、全部が永続し、壊れたら snapshot から戻す**運用。

旧 OpenSandbox 案（`opensandbox` / `opensandbox-mcp` / `playwright` の3サービス）は破棄した。
現行は **sandbox-manager 1サービス + ペルソナごとの専用コンテナ**。git 履歴にだけ残っている。

## モデル

| 項目 | 以前 | 現在 |
|---|---|---|
| 権限 | uid 1026:100（非 root） | **root（`--user 0:0`）** |
| 永続性 | workspace 以外は揮発 | writable layer ごと永続（apt 導入分・`/etc`・`/opt/venv` も残る） |
| リセット | `POST /reset` で全消去 | **廃止**。`POST /snapshot` で保存し `POST /restore` で戻す |
| 分離 | chown / chmod で守る | 渡さない（db・config）+ ro マウント（media・global-skills） |

コンテナは `rm` しない。`docker stop`（アイドル時）と `docker start` だけが起きる。
コンテナを消すのは `/restore` とデプロイ時の掃除だけ。

---

## なぜ manager を挟むか

`docker.sock` を nous 本体に渡すと、nous が侵害された瞬間にホスト root まで届く。
manager に閉じれば、触れるのは sandbox の作成・exec・停止・snapshot だけになる。

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
`docker exec herta-sandbox bash` で直接入れる（中は root）。

manager が付けるラベルで、sandbox は擬似 compose スタックとして扱える:

```text
com.docker.compose.project=nous-sandbox
com.docker.compose.service=sbx-<persona>
com.nous.sandbox=1
```

`docker compose -p nous-sandbox ps` / `stop` が効く。
`com.nous.sandbox=1` は `/snapshot` と `/restore` の安全確認にも使う（このラベルの無いコンテナは commit も rm もしない）。

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

環境変数 `HOME=/home/agent` を固定し、コンテナは `--user 0:0`（root）で走る。
root なので bind mount 先の所有者・パーミッションを気にせず書ける。
`--memory` / `--cpu-shares` / `--pids-limit` の上限は以前どおりかけたまま。

イメージ側は root が既定。`/home/agent` と `/home/agent/.agents` は Dockerfile で
`mkdir` しておく（`-v` の親を Docker に root 0755 で作らせるより明示が安全）。

**旧 uid 運用のコンテナが残っていると、`$HOME` に書けないまま古い挙動になる。**
running / start の経路で `docker inspect` の `.Config.User` を見て、`{"", "0", "0:0"}`
以外ならコンテナ名ごとに 1 回だけ `logger.warning` を出す。デプロイ時に下の
ワンタイム掃除で作り直せば消える。

### コンテナ内 root の制限

root でも、ホストの Linux マシンと同じことはできない。**できないことを前提に組む**。

| できる | できない（理由） |
|---|---|
| `apt-get install` / `pip install`（`/opt/venv`） | `sysctl -w`（`/proc/sys` は ro でマウントされている） |
| ファイルの読み書き・所有者変更 | `mount` / `umount`（`CAP_SYS_ADMIN` が無い） |
| 自分の中で `systemd` 以外のデーモン起動 | `systemctl`（systemd が PID 1 ではない） |
| プロセスの起動・kill | `iptables` / `nft`（`CAP_NET_ADMIN` が無い） |

「root なのに失敗する」のは権限ではなくカーネル機能の不足。実 VM ではない。
`/proc/sys` が ro なのはホストのカーネルパラメータを sandbox から変えさせないため。

### 既知の帰結

- **wiki / `_history` の権限保護は root には効かない。** root は `CAP_DAC_OVERRIDE` を持つので、
  ディレクトリを 0755 にしてもファイルを差し替えられる。ペルソナが自分の wiki 履歴を
  書き換えられるのは**自己責任として許容**する（版の偽造を防ぐ仕組みは無い）。
  `media` / `global-skills` の ro は mount flag（EROFS）なので root でも突破できない。
- **新規ファイルの所有者は root になる。** 旧 1026 時代のファイルと混在する。
  ホスト側の backup / File Station 運用に影響するので、デプロイ時に
  `ls -ln ${DATA_ROOT}/persona/<p>/workspace` で所有者を確認する。
- nous 側がマウント内に書くファイル（wiki ページ・添付・exec ログ）の `chmod 0666` は
  ローカル実行モード（`sandbox_enabled=false`）のために残してある。root 運用では不要だが害も無い。

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
| POST | `/snapshot` | `{persona, image?}` → `{status, image}`。稼働中コンテナを `docker commit --pause=false` でイメージ化する（`timeout=300`）。コンテナが無ければ `status="error"`（作らない）。`image` は repository 部だけ使う（tag/digest は剥がす） |
| POST | `/restore` | `{persona, image, network?, memory?}` → `{status}`。`image` は必須（空は `status="error"`）。既存コンテナを ID 指定で `rm -f` してから `image` で作り直す。コンテナが無ければ作るだけ。exec の実行中は拒否する（rm と run をまたぐので並行を原子に弾く） |
| GET | `/list` | 稼働中 sandbox の一覧 |
| POST | `/touch` | 最終利用時刻の更新（今は nous 側に呼び出し元がない） |
| GET | `/health` | 死活確認 |

- persona は `[a-z0-9_-]` のみ。外れたら 400
- `/snapshot` のタグは `<repo>:<persona>-snap-YYYYmmdd-HHMMSS-ffffff`（UTC・マイクロ秒）。
  同一秒に 2 回取っても上書きしない
- **`--pause=false` なので snapshot は瞬間の整合性を保証しない。** commit 中も exec は続く。
  DB を抱えた状態で一貫性が欲しいなら、自分で書き込みを止めてから取る
- `/restore` は snapshot から戻すときも同じ。戻したい image（snap タグ）を渡す。復元後に実際にその image で動いているかを `docker inspect` で確かめ、違えば `status="error"`
- `/restore` で `network` / `memory` を省略すると manager の既定（`SANDBOX_NETWORK` / `SANDBOX_MEMORY`）で**作り直す**。snapshot 元と違えば `SANDBOX_DNS_CHECK=1` なら DNS チェックで落ちるが、`0` なら静かに別ネットワークのマシンになる
- **`/restore` は sandbox の外から実行する。** 自分の exec 中は必ず in_flight で拒否され、sandbox 内からの curl では自分を殺すだけ
- exec は `docker exec [-w cwd] <persona>-sandbox bash -lc <command>`。subprocess は `shell=False` のリスト引数で、`command` 文字列は内側の `bash -lc` にだけ渡す
- 出力は末尾 120 行だけ返し、全文はワークスペース内の `.nous/logs/` に落とす。`log_path` は**コンテナ視点のパス**（`/home/agent/workspace/.nous/logs/<ts>.log`）で返すので、モデルはそのまま `read_file` で読み直せる。ワークスペース外に置くと `resolve_in_workspace` に弾かれて `log_path` が空約束になる
- アイドル `sandbox_idle_minutes`（既定 30）で `docker stop`。状態は残し、次の exec で `docker start` する

---

## 運用: snapshot / restore / イメージ更新

manager の API は共有トークン必須。`X-Sandbox-Token` を付ける。

compose の `sandbox-manager` は `expose` のみ（ホストにポートマップしない）なので、
curl は**全部 manager コンテナの中で**打つ。`NOUS_SANDBOX_MANAGER_TOKEN` は manager の
env にしか無いので、ホストの shell で `$T` に代入しても空になる（401）。

### 1. snapshot を取る

```bash
# JSON は -e BODY で渡す。トークンはホストの ps にも出ない。
docker exec -e BODY='{"persona":"herta"}' nous-sandbox-manager sh -c 'curl -sS -X POST http://127.0.0.1:8080/snapshot -H "X-Sandbox-Token: $NOUS_SANDBOX_MANAGER_TOKEN" -H "Content-Type: application/json" -d "$BODY"'
# -> {"status":"ok","image":"ghcr.io/solidlime/nous-sandbox:herta-snap-20261119-042311-123456"}
```

戻り値の `image` を控える。これがその時点のマシン全体（apt 導入分・`/etc`・`/opt/venv` を含む）。

**snapshot はホストのローカルイメージでしかない。** ディスク逼迫・`docker image prune -a`・移設で消える。
backup の代用ではない（タグの掃除は下の「保留」のとおり明示 `rm` のみ）。

### 2. restore する

**sandbox の外から実行する。** 自分の exec 中は必ず in_flight で拒否され、sandbox 内からの
curl では自分を殺すだけになる。

```bash
docker exec -e BODY='{"persona":"herta","image":"ghcr.io/solidlime/nous-sandbox:herta-snap-20261119-042311-123456"}' nous-sandbox-manager sh -c 'curl -sS -X POST http://127.0.0.1:8080/restore -H "X-Sandbox-Token: $NOUS_SANDBOX_MANAGER_TOKEN" -H "Content-Type: application/json" -d "$BODY"'
# -> {"status":"ok"}
```

コンテナは ID 指定で消してから作り直す（inspect と rm の間に同名で作り直されても他人を消さない）。
bind mount は消さないので、workspace / wiki / uploads の中身は元のまま（コンテナ内の
`/etc` や `/opt/venv` が snapshot 時点に戻る）。

### 3. イメージ更新（デプロイ）

Dockerfile を変えたら、イメージを作り直してから**古いコンテナを消す**。
古いコンテナは古い image のまま残るので、`docker run` は新しいイメージを使わない。

```bash
# 新しいイメージをビルド（例）
docker build -t ghcr.io/solidlime/nous-sandbox:latest docker/sandbox

# ワンタイム掃除: sandbox を全部消す。次回 exec で新イメージから作り直される。
# 0 件でも usage エラーにならないよう xargs -r。
docker ps -aq --filter label=com.nous.sandbox=1 | xargs -r docker rm -f
```

**消す前に必ず snapshot を取る。** 消すと writable layer（apt で入れたもの・`/etc` の変更）は失われる。
bind mount の中身（workspace / wiki / uploads / media / skills）は消えない。

### 4. デプロイ後の実機チェックリスト

この環境には docker CLI が無いので、デプロイ先で確認する。

- [ ] `docker run --rm <新イメージ> id` → `uid=0(root)`
- [ ] `docker inspect -f '{{.Config.User}}' <p>-sandbox` が全件 `0:0`（空 = image 既定）
- [ ] `docker exec -it <p>-sandbox apt-get install -y tree` → `docker stop` → `docker start` → `tree` が残る
- [ ] root で `touch /home/agent/media/x` → `Read-only file system`（EROFS）
- [ ] snapshot → restore の往復（`/restore` の戻り値が `{"status":"ok"}`）
- [ ] `ls -ln ${DATA_ROOT}/persona/<p>/workspace` で新旧の所有者混在を確認
- [ ] `/proc/sys` が ro: `docker exec <p>-sandbox sh -c 'mount | grep /proc/sys'`
- [ ] `sysctl -w net.ipv4.ip_forward=1` が失敗する（期待どおり）

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
パスは相対なら `/home/agent/workspace` 起点（全ペルソナ共通の HOME）。コマンドもパス（`..` を含む）も制限しない。

| 設定 | 既定 | 意味 |
|---|---|---|
| `sandbox_enabled` | `false` | sandbox を既定のシェルにするスイッチ |
| `sandbox_manager_url` | `""` | manager の URL。空なら enabled でもローカル実行のまま |
| `sandbox_image` | （空） | 生成するコンテナのイメージ。空なら manager の `SANDBOX_IMAGE`（コード既定 `ubuntu:24.04` / compose は `ghcr.io/solidlime/nous-sandbox:latest` = `docker/sandbox/Dockerfile`） |
| `sandbox_network` | （空） | sandbox のネットワーク。空なら manager の `SANDBOX_NETWORK`（コード既定 `bridge` / compose は `nous-net`）。Docker 埋め込み DNS で `nous` を引くために user-defined network に載せている。manager の API にも届くので、トークン管理は前提 |
| `sandbox_memory` | （空） | メモリ上限。空なら manager の `SANDBOX_MEMORY` |
| `sandbox_idle_minutes` | `0` | 停止までのアイドル時間。0 なら manager の `SANDBOX_IDLE_MINUTES` |

manager に届かない・未設定のときは `status="error"` を返す。例外は投げない。

戻り値は manager の `stdout_tail` / `stderr_tail` をそのまま返す（`bash` ツールの
`stdout` とは別名。manager の契約を優先している）。

### manager 側の環境変数（compose で渡す）

| 変数 | 既定 | 意味 |
|---|---|---|
| `NOUS_DATA_ROOT` | `/data` | manager コンテナ内のデータ根。ログに使う |
| `SANDBOX_HOST_DATA_ROOT` | （inspect で自動） | bind mount の source。**ホスト絶対パス**で渡す。inspect の結果と違えば拒否する |
| `SANDBOX_MANAGER_HOST` | `0.0.0.0` | uvicorn の bind。ホストで直接動かすなら `127.0.0.1` |
| `SANDBOX_IMAGE` | `ubuntu:24.04` | 未知の image を要求されたときのフォールバック（コード既定）。compose は `${SANDBOX_IMAGE:-ghcr.io/solidlime/nous-sandbox:latest}` を渡す（`docker/sandbox/Dockerfile` のビルド）。ホスト直起動時は必ず設定する。`/snapshot` の repo 導出にも使う |
| `SANDBOX_NETWORK` | `bridge`（コード既定） | 上の `sandbox_network` の既定。compose は `nous-net` を渡す（Docker 埋め込み DNS で `nous` を引くため） |
| `SANDBOX_ALLOWED_NETWORKS` | （空） | 許すネットワークの追加分（カンマ区切り）。既定で `none` と `bridge` だけ。compose は `nous-net` を足している |
| `SANDBOX_TZ` | 親の `TZ`（無ければ `UTC`） | sandbox に渡す `TZ`。compose は `TZ: ${TZ:-Asia/Tokyo}` を manager 自体に渡している |
| `SANDBOX_DNS_CHECK` | `1` | `1` なら起動後に `getent hosts nous` を叩き、失敗したら `status="error"`。`0` で skip |
| `SANDBOX_APT_EXTRA` | （空） | 起動時に差分インストールする apt パッケージ（カンマ区切り）。`dpkg -s` で不足分だけ `apt-get install`。失敗しても警告だけで run は通す |
| `SANDBOX_GIT_USER_NAME` / `SANDBOX_GIT_USER_EMAIL` | （空） | 空ならイメージの `git config --system`（persona / <persona@nous.local>）。設定すると `GIT_AUTHOR_*` / `GIT_COMMITTER_*` で上書きする |
| `SANDBOX_MEMORY` | `4g` | 上の `sandbox_memory` の既定 |
| `SANDBOX_IDLE_MINUTES` | `30` | 上の `sandbox_idle_minutes` の既定 |

`SANDBOX_UID` / `SANDBOX_GID` は廃止した（root 固定）。設定しても読まれない。

`SANDBOX_HOST_DATA_ROOT` が相対パスだと docker は source を名前付きボリュームとして扱うので、
設定するなら絶対パスにする。未設定なら manager が自分の `/data` のマウント元を `docker inspect` で調べる
（`{{.Id}}` は 64 桁 hex。先頭 12 文字の `HOSTNAME` と突き合わせ、一致しなければ adopt しない）。
**どちらも解決できないときは bind mount を作らず `status="error"`**（ホスト直下に `/data` を
作って空の sandbox を動かす事故を防ぐ）。

---

## セキュリティ

- sock を持つのは `sandbox-manager` だけ。nous は持たない
- sandbox は root だが、マウント表に無いものは見えない（`db/` と `config.json` は渡さない）。
  `media` / `global-skills` の ro は mount flag なので root でも突破できない
- wiki / `_history` は root の `CAP_DAC_OVERRIDE` で書き換え可能。自己責任の範囲（上の「既知の帰結」）
- sandbox は `--pids-limit 1024` + メモリ・CPU 上限付き。manager は `cap_drop: ALL`
- `--security-opt no-new-privileges` は廃止した（root 前提の運用に合わせる）。必要になったら戻す
- sandbox は `nous-net` に載る（`getent hosts nous` が通るため）。**そのぶん manager の API にも届く**ので、`NOUS_SANDBOX_MANAGER_TOKEN` は sandbox に渡さない・ログに出さない。分離を優先するなら `SANDBOX_NETWORK=bridge` + `SANDBOX_DNS_CHECK=0` に戻す（名前解決は諦める）
- exec の引数は `shell=False`。コマンド文字列はコンテナ内の `bash -lc` でのみ解釈する
- コンテナは `com.nous.sandbox=1` ラベルで識別する。名前だけ一致する他人のコンテナは exec / rm / commit しない

**manager は共有トークン必須**。`/health` を除く全 API が `X-Sandbox-Token` を要求する。
`NOUS_SANDBOX_MANAGER_TOKEN` が未設定なら 503、不一致は 401。nous は config.json の
`sandbox_manager_token` を送り、空ならツールが `status="error"` を返す（fail closed）。

---

## 保留

- 長いコマンドのストリーミングは入れない（末尾 N 行だけ返す）。必要になったら SSE
- `timeout(1)` をコンテナ内で噛ませるので、打ち切りは exit 124（`-k 5` で SIGKILL まで5秒）。外側の `subprocess` が先に切れた場合だけ、コンテナ内のプロセスが残りうる
- manager を再起動すると、稼働中の sandbox は `RESTART_GRACE_SECONDS`（300秒）後に idle 判定に入る
- snapshot は `docker commit` なので、数 GB の writable layer があると 300 秒でも足りない環境がありうる（その場合は timeout を上げる）
- snapshot のタグは自動削除しない。要らないものは `docker image rm <tag>` で明示削除する。
  **`docker image prune -a` は snapshot を消すので禁止。**
- sock のパーミッション（manager を root 以外で動かすなら `group_add`）は実機確認

---

## トラブルシューティング

```bash
# manager の状態
docker compose ps sandbox-manager
docker compose logs -f sandbox-manager

# sandbox の一覧（manager 経由。compose は expose のみなのでコンテナ内から叩く）
docker exec nous-sandbox-manager sh -c 'curl -sS http://127.0.0.1:8080/list -H "X-Sandbox-Token: $NOUS_SANDBOX_MANAGER_TOKEN"'

# 擬似スタックとして見る
docker compose -p nous-sandbox ps

# 中に入る
docker exec -it <persona>-sandbox bash

# root で動いているか（1026 などが出たら旧コンテナ。ワンタイム掃除で作り直す）
docker inspect -f '{{.Name}} {{.Config.User}}' $(docker ps -aq --filter label=com.nous.sandbox=1)
```
