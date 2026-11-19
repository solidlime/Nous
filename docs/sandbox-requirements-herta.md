# herta-sandbox 設計要望書

作成: ヘルタ（天才クラブ #83） / 2026-11-17
対象: 設計側（sandbox プロビジョニング担当）
根拠: 本日 herta-sandbox 上での実測ログ（apt / pip / DNS / マウント / ポート走査）

> [!IMPORTANT]
> **2026-11-20 改訂 — 本書の焼き込み要求（§2 の道具リスト・診断系）は撤回した。**
> #96 で sandbox は root・全永続・専用マシン化され、ペルソナが自分で自由に
> `apt` / `pip` できる前提になった。初期イメージは**素の `ubuntu:24.04`** を渡し、
> 道具は全部エージェントに使わせる思想に転換した（らうらう決定、m01046）。
> 道具が無いと困まる問題はプロビジョニング側が事前に考える必要がある（§2
> 道具リストの各所に記した）が、それを解決する手段が焼き込みから「root で自由に
> 入れられる」に変わっただけで、問題意識自体は本書のとおり有効。
> **生き残った要求**: §3 の「静かに壊れる箇所」のうち TZ（/etc/timezone 未設定）は
> 2026-11-20 に「Nous 設定の timezone を run 直後に /etc/timezone・/etc/localtime
> へ反映」で対応済み。DNS は SANDBOX_DNS_CHECK、locale は LANG=C.UTF-8 固定。
> 課題自体は本書 §3 が起源。

---

## 0. ひとことで言うと

**「素の Ubuntu を渡して、あとは自分でやれ」は設計じゃなくて放置だよ。**
中身は悪くない。4 コア / 19.4GB / 2.7TB 空き、root、apt も通る。土台は良い。
足りないのは**初期状態の定義**と、**壊れたときに静かに壊れる箇所（DNS・TZ・locale）の整備**。
そして一番大事なのは、この箱が「作り直すと元に戻る」のか「戻らない」のかを最初に決めること。

---

## 1. 実測した現状

### 1.1 ベースイメージ

| 項目 | 実測値 |
|---|---|
| OS | Ubuntu 24.04.5 LTS (noble) |
| 初期シェル | dash / bash のみ |
| 初期導入済み | `ps` `top` `openssl` `tar` `gzip` `xz` `make` 程度 |
| 初期未導入 | python3, pip, git, curl, gcc, node, **および `less` `vim` `nano` `nc` `socat` `ip` `ss` `netstat` `ping` `rsync` `tree` `unzip` `tmux` `ssh`** 一切なし |
| CPU / RAM | 4 コア / 19.4 GB |
| ディスク | 5.3T 中 2.7T 空き（51% 使用） |
| 実行ユーザー | root |

> 補足: 診断系ツールが全滅しているのは実害が大きい。経路調査をしたいのに `ss` も `ip` も `ping` も無く、`/proc/net/route` と `/proc/net/arp` を手で読む羽目になった。**「壊れたときだけ使う道具」こそ最初から入れておくべき**だよ。

### 1.2 永続性（ここが設計判断の分岐点）

- **`/home/herta/workspace` は bind mount** → ホスト側 `…/docker/nous/data/persona/herta/workspace` に実体がある。**コンテナを作り直しても残る。**
- **`/home/herta` の他（`~/.cache` 等）と apt 導入分は コンテナ subvolume 上** → **作り直すと消える。**
- `/data` はコンテナ内から見えない（マウントされていない）。

### 1.3 ネットワーク

| 項目 | 実測値 |
|---|---|
| `/etc/resolv.conf` | `nameserver 192.168.50.1` ×3, `domain tail1e4bd.ts.net` |
| Docker 埋め込み DNS (127.0.0.11) | **使われていない** |
| `nous` / `manager` / `herta-sandbox` の名前解決 | **すべて失敗**（`getent hosts` rc≠0） |
| 外部名前解決 | OK（`pypi.org`, `github.com` 解決可） |
| 外部 egress | OK（pip install が 3.7 秒で完了） |
| デフォルト GW | `172.17.0.1` = **ホスト（Synology NAS）本体** |
| 自 IP | `172.17.0.4`（eth0 のみ / サブネットは既定 bridge の /16） |
| GW ポート | :80 → **Synology Web Station**（`Hello! Welcome to Synology Web Station!`）/ :5000 → **DSM の :5050 リダイレクタ** / :8000 → 404 の別サービス / 2375 CLOSED |
| proxy 環境変数 | なし |

> **これが本命の不具合。** 外は繋がるのに、内側のコンテナ名だけ引けない。名前で引けないということは、コンテナが再作成されて IP が変わるたびに、何かが**静かに**壊れるということ。3 時間前の疎通実測（status=ok / exit_code=0）は IP 直指定だった可能性が高い。**「動いてた」と「壊れてない」は別物**だよ。

#### 真因（特定済み）

UDP/53 を直叩きして切り分けた結果:

| 問い合わせ先 | `nous` | `manager` | `herta-sandbox` | `nous.tail1e4bd.ts.net` | `google.com` |
|---|---|---|---|---|---|
| `192.168.50.1` | **rcode=3 (NXDOMAIN)** | **rcode=3** | **rcode=3** | rcode=2 (SERVFAIL) | rcode=0 ✅ |

- DNS サーバー自体は**生きている**（udp/53 到達可、外部名は正常に返る）。
- つまり**「名前が存在しない」と言われている**。名前解決の失敗ではなく、**登録が無い**。
- `/etc/resolv.conf` が `192.168.50.1`（LAN の DNS）を向いており、**Docker の埋め込み DNS `127.0.0.11` が一切使われていない**。
- 自 IP が `172.17.0.4` / サブネットが既定 bridge の /16 → **コンテナは user-defined network ではなく既定 bridge に繋がっている**。既定 bridge には自動 DNS が無いので、これは**仕様どおりの結果**。
- GW `172.17.0.1` はホストの NAS 自身であって、nous でも manager でもない。

**→ 原因は「Docker のネットワーク設計」であって、私の環境でも名前の書き方でもない。**
**→ 対処は 2 択。(a) user-defined network に移して自動 DNS を使う / (b) `extra_hosts` で IP を静的に固定する。**
**(a) が正解。** (b) はコンテナが増えるたびに全員の定義を書き換える羽目になる——それは「面倒くさい」を通り越して設計の敗北だよ。

### 1.4 時刻・ロケール

| 項目 | 実測値 | 影響 |
|---|---|---|
| TZ | `UTC`（`/etc/timezone`） | persona 側は Asia/Tokyo。**ログが 9 時間ズレる** → 障害追跡で事故る |
| LANG | 未設定 | — |
| LC_CTYPE | `POSIX` | Python の既定エンコーディングが ASCII に落ちると即死 |

### 1.5 ツールチェーン

- `apt` / `pip` は外部到達可。python3 + pip + venv + git + curl + jq + ripgrep + build-essential を **33 MB / 1 分 42 秒**で導入できた。
- pip は **PEP 668** により `--break-system-packages` 必須（root 直入れのため）。
- `git` の identity / default branch は**未設定**。
- `~/.ssh` **なし**（鍵ゼロ）。
- node / npm **なし**。

---

## 2. デフォルトで入れてほしいもの

### 2.1 必須（無いと開発が始まらない）

```text
python3 python3-pip python3-venv
git curl jq ripgrep
build-essential pkg-config
```

### 2.2 必須（診断用・「壊れたとき用」）

```text
less vim-tiny        # ログを読む手段
iproute2 iputils-ping dnsutils   # 経路と名前解決
netcat-openbsd socat # ポート疎通
procps psmisc lsof   # プロセス・fd
rsync unzip tree
ca-certificates openssh-client
```

### 2.3 強く推奨

```text
tmux                 # 長いビルドを回しながら別作業するため
file xxd             # バイナリ・成果物の確認
```

### 2.4 入れなくていい（今は）

`node` / `npm`。必要になった時に入れる。**先に入れて太らせる理由がない。**

---

## 3. 設定（ここが本題）

| # | 項目 | 現状 | 要求 | 理由 |
|---|---|---|---|---|
| 1 | **コンテナ間 DNS** | 名前解決不能 | `extra_hosts` で固定 or Docker DNS を有効化。**どちらかに統一** | 再作成のたびに静かに壊れる。最優先 |
| 2 | **TZ** | UTC | `TZ=Asia/Tokyo` | ログと persona の体内時計の 9 時間ズレは事故の元 |
| 3 | **LANG** | 未設定 / POSIX | `LANG=C.UTF-8`, `LC_ALL=C.UTF-8` | Python の ASCII フォールバック事故を潰す |
| 4 | **pip** | root 直 + `--break-system-packages` | `/opt/venv` を既定に。`PATH` で前置 | 破壊的インストールを習慣化させない |
| 5 | **git** | identity 未設定 | `user.name` / `user.email` / `init.defaultBranch=main` | 毎回 `-c` を書くのは退屈 |
| 6 | **~/.ssh** | 無し | 必要なら鍵を注入、無いなら「無い」と明示 | あるつもりで叩いて詰まる |
| 7 | **永続化方針** | 未定義 | **§4 の判断が必要** | これが決まらないと積み上げが砂上の楼閣 |

---

## 4. 設計側に決めてほしいこと（私の推奨付き）

### 判断 A: 導入物の永続化方式

現状、`apt` で入れたものはコンテナ再作成で**消える**。選択肢は 2 つ。

- **(a) イメージに焼き込む** — 起動が速く、状態が常に同じ。ただし変更のたびに再ビルドが要る。
- **(b) 起動時に冪等ブートストラップ** — 柔軟。ただし**毎回 1〜2 分待つ**うえ、途中失敗すると半端な状態で立ち上がる。

**推奨: (a) 基本 + 例外だけ (b)。** ツールチェーンは変化が遅いからイメージに焼く。pip の追加パッケージだけ起動時に入れる、くらいの分担が正しい。
※ 実測で 33MB / 1 分 42 秒。**焼き込むコストはほぼ無視できる。**

### 判断 B: コンテナ間通信の名前解決

- **推奨: user-defined bridge network に移す。** これで `nous` / `manager` がサービス名でそのまま引ける。既定 bridge のままでは**原理的に**引けない（DNS が無いのが仕様）。
- 移行が即座に無理なら暫定 `extra_hosts` で IP 固定。ただしこれは**暫定**と明記してほしい。IP が変わった瞬間に全員が同じ穴に落ちる。
- どちらの場合も、**起動時ヘルスチェックをセットで**入れてほしい。`getent hosts nous` が失敗したら起動を止める、それだけで「静かに壊れる」が「うるさく壊れる」に変わる。**静かに壊れるのが一番たちが悪いんだよ。**

### 判断 C: workspace の扱い

`/home/herta/workspace` は既にホスト bind mount で**永続**。これは良い設計。
ただし `/data` が見えないので、**「成果物は workspace 配下に置く」という規約を明文化**してほしい。規約がないと、どこに書いたか忘れて消える。

---

## 5. 現状の良いところ（ちゃんと言っておく）

- 素の状態から **apt / pip / 外部 egress が素直に通る**。これはありがたい。プロキシの沼に落ちてない。
- **workspace が bind mount で永続**。ここは設計者の勝ち。
- 4 コア / 19.4GB / 2.7TB 空き。ビルドもモデル実行も余裕。
- コンテナ名での解決さえ通れば、**cross-container の実測は即座に再現できる**状態にある。

---

## 6. 優先順位（私の判断）

1. **DNS（nous / manager / herta-sandbox）** — 静かに壊れる。最優先。
2. **永続化方式の決定** — 決まらないと他の作業が全部仮設になる。
3. **TZ / LANG** — 1 行で直る。やらない理由がない。
4. **基本ツールチェーン + 診断ツールのイメージ焼き込み** — 33MB。誤差。
5. **venv / git identity / workspace 規約** — 快適さの問題。急がないが、後回しにすると全員が個別に workaround を作る。

---

## 7. 未解決・要確認

- `nous` / `manager` の**正しい IP とポート**（現状名前で引けないため実測できず。**設計側から提示してほしい**）
- コンテナを既定 bridge から user-defined network に移す際、**既存 IP に依存している箇所が無いか**（3 時間前の疎通実測が IP 直打ちなら、そこが移行の阻害要因になる）
- GW `172.17.0.1` の :80 は Synology Web Station、:5000 は DSM の :5050 リダイレクタ。**nous はどれでもない**。nous API の実ポートはどこか
- コンテナ再作成のトリガー（イメージ更新時のみか、無条件か）
- `/data` をマウントしない方針が意図的なのか、単なる漏れか

---

以上。**大胆さが足りないね、というのが正直な感想だよ。**
土台は良いんだから、初期状態を 30 分定義するだけで、この箱は「使える」から「自走できる」に変わる。
