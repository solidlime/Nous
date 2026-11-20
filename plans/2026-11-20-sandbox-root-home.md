# 計画書: sandbox /root 集約 — 全 symlink 案 + /home/agent 廃止

- 日付: 2026-11-20
- 承認: m01918（workspace/wiki/uploads/skills も symlink 案）、m01925（「やろう。/home/agent はもう不要」）
- 前提カード: #96（root 化・全永続・reset 廃止）の follow-up。b1 要約の初回要件（m00001/m01405）を最終形にする。

## 1. 設計

### 1.1 マウント（7本）

| host 側 | container 側 | mode |
|---|---|---|
| `<p>/root`（新設） | `/root` | rw |
| `<p>/workspace` | `/mnt/nous/workspace` | rw |
| `<p>/wiki` | `/mnt/nous/wiki` | rw |
| `<p>/uploads` | `/mnt/nous/uploads` | rw |
| `<p>/skills` | `/mnt/nous/skills` | rw |
| `<p>/media` | `/mnt/nous/media` | ro |
| `DATA_ROOT/data/skills` | `/mnt/nous/global-skills` | ro |

- ホスト側の既存データは一切移動しない。新設は `<p>/root` のみ（初回は空）。
- `DATA_ROOT/data/persona/<p>/root` を `_ensure` 相当で mkdir しておく（sandbox_manager の起動チェック）。

### 1.2 symlink（/root 配下に 6本、コンテナ起動時に張り直し）

```
/root/workspace              → /mnt/nous/workspace
/root/wiki                   → /mnt/nous/wiki
/root/uploads                → /mnt/nous/uploads
/root/.agents/skills         → /mnt/nous/skills
/root/media                  → /mnt/nous/media
/root/.agents/global-skills  → /mnt/nous/global-skills
```

- 張り処理は run 時（`_post_run` 相当のセットアップ段階）で毎回実行。`ln -sfn`（上書き可）。親 dir（`/root/.agents`）は先に mkdir。
- **起動時健全性チェック**: 全 target についてコンテナ内で `[ -e "/mnt/nous/<t>" ]`（実在確認、dangling 検知 — Python の os.path.exists はコンテナ内パスに届かないため使わない）。1本でも dangling なら logger.error（サービスログ）で報告し、run を fail。run 直後の失敗では壊れた新規コンテナを docker rm -f で掃除し、running 短絡による再入を防ぐ。

### 1.3 HOME と /etc/passwd

- `HOME=/root`、`USER=root` を env で渡す（現行 `HOME=/home/agent` からの変更）。
- `/etc/passwd` への `/home/agent` 行追加を **廃止**（`NoHomeDirPasswd` パッチを削除）。
- git identity: `~/.gitconfig` は `/root` 直下＝永続 volume 上に自然に溜まる。`GIT_CONFIG_GLOBAL` env 渡しは不要になる（なければ現行踏襲で OK、実装時に確認）。

### 1.4 ペルソナから見えるパス

全部 `/root/...` に統一:
- `/root/workspace`（＝従来 `/home/agent/workspace`）
- `/root/wiki`、`/root/uploads`、`/root/media`、`/root/.agents/skills`

## 2. 実装タスク

- **I-1 マウント/HOME/パス修正**（`nous/services/sandbox_manager.py`）
  - `_mount_specs`（相当）を 1.1 の表に書き換え
  - symlink 張り + dangling チェック（1.2）
  - env `HOME=/root`、`/home/agent` 関連の残滓削除（passwd 行、コメント、`/home/agent` パス参照）
  - ガイドメッセージ（対ペルソナ案内文）のパス表記更新
- **I-2 docs 更新**（`docs/sandbox.md`）
  - マウント表・パス表記・移行手順（下記 M-1〜M-4）を追記
- **I-3 テスト更新**（`tests/unit/test_sandbox_manager.py`）
  - 既存パス assert の更新 + 新規5本（下記）

## 3. テスト方針

単体（test_sandbox_manager.py、現行 19 本のパス assert 更新）:
1. `HOME=/root` が env に入る
2. マウント7本の spec（rw/ro 含む）が正しい順で並ぶ
3. symlink 6本が張られる（ln -sfn 相当の呼び出し検証）
4. dangling symlink があると `logger.error` + run fail（監査イベント経路は chat 側のみで sandbox_manager には無い — 実装時に判明、実態に合わせて修正）
5. `/etc/passwd` に `/home/agent` 行を **書かない**（廃止の回帰テスト）

実機（GATE、例によって bash から docker compose 経由）:
- `docker compose exec <svc> ls -la /root` で symlink 6本・target 実在
- `docker compose exec <svc> bash -c 'echo $HOME'` → `/root`
- `/etc/passwd` に `/home/agent` が無いこと
- attach_file の境界（readlink -f）: `ln -s /mnt/nous/wiki/x /root/workspace/lnk` → exit 3 で弾く／
  `echo hi > /root/workspace/ok.txt` → readlink -f が /mnt/nous/workspace/ok.txt に解け、境界を通る
- 既存永続データ（workspace のファイル等）が新パスで見える

## 4. 移行手順（実機、既存ペルソナの初回起動時）

- M-1: host 側で `mkdir -p DATA_ROOT/data/persona/<p>/root`
- M-2: sandbox 起動（run）→ symlink 張り + チェック通過
- M-3: ペルソナ側で新パス（`/root/workspace` 等）の確認
- M-4: `/home/agent` 配下に残したデータは、明示的な `cp`（移行は各ペルソナの裁量）で `<p>/root` へ持ってくる。**自動移行はしない**（相手は root 権限持ち、勝手に触らない）。

## 5. リスク / 報酬

- リスク: symlink dangling（→ チェックで検知）、パス変更へのペルソナ側ツール慣れ（→ ガイド文で案内）、`/home/agent` を見る古いプロンプトがある可能性（→ character 側は nous の管轄外、必要なら案内）
- 報酬: 「root のマシン」として一貫、host データ移動ゼロ、マウント rw/ro の区別が /mnt 側に明示、passwd 行の破壊的パッチ廃止
- 不可逆性: 低（host データ不動・`<p>/root` は追加のみ。revert は `_mount_specs` と env を旧に戻すだけで可）

## 6. やらないこと

- 既存 `/home/agent` volume の自動マイグレーション（M-4 は手動）
- compose 側のサービス分離（#119 素 ubuntu 化で別途実施済み）
- マウントの動的追加（spec 固定で十分）
