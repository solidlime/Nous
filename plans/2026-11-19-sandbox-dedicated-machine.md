# sandbox: persona dedicated machine (root, full persistence, reset removal) rev2

Date: 2026-11-19 (rev2: reflects 8 BLOCK findings from Ruan Mei)
Approved by: raurau (container VM なしの継続運用 / reset 廃止 / db-config 以外は開放)
Pre-review: Ruan Mei BLOCK -> this revision adds /restore, --pause=false + timeout=300, old-container sweep, etc.
Triage: full-scale -> REVIEW phase requires Ruan Mei PASS again

## 決定済みの方針（不変）

sandbox を「隔離された使い捨てコンテナ」から
「ペルソナに貸し切る 1 台の Linux マシン」へ転換する。

1. root 権限: コンテナを `--user 0:0` で走らせる。uid 1026 運用を廃止
2. 全ディレクトリ永続化: コンテナを rm しない運用。writable layer（apt 導入分・/etc・/opt/venv を含む全変更）は残り続ける
3. reset 廃止・snapshot/restore 新設: 全消去 API は消す。「壊れたら snapshot から復元」の往復を API で完結させる（sock は manager に閉じたまま、ペルソナが HTTP で自分のマシンを守れる）
4. 分離: db/ と config.json は渡さない。wiki/_history の dir 権限保護は root には無効（CAP_DAC_OVERRIDE）= 自己責任許容。media と global-skills の ro マウントは実効性あり（mount flag の EROFS。root でも remount に CAP_SYS_ADMIN が必要）
5. コンテナ内 root は実マシン相当ではない: /proc/sys は ro（sysctl -w 不可）。mount / systemctl / iptables は不可（CAP_SYS_ADMIN 不在）。docs に明記し「root なのに失敗する」問い合わせを防ぐ

## 変更ファイル

### 1. nous/services/sandbox_manager.py（主変更）

_ensure_inner (L420-):
- `--user 0:0` を固定で渡す（SANDBOX_UID / SANDBOX_GID の env 参照を全廃）
- `--security-opt no-new-privileges` を除去
- `--memory` / `--cpu-shares` / `--pids-limit` は維持
- マウント先 mkdir 後の os.chmod(target_dir, 0o777) を止める
- 既存コンテナの .Config.User 検査は残す: running/start 経路で
  user が {"", "0", "0:0"} に含まれないなら warning を 1 回だけ出す
  （毎 exec ではなくコンテナ名ごとに 1 回。小さな set で管理）

_fix_home / _fix_mount_perms / _home_fixed / _home_warned (L225-296): 全廃
- root 化で chown は不要。呼び出し側（inspect 時・_post_run）も削除

_write_log (L554-557):
- os.chmod(path.parent, 0o777) と os.chmod(path, 0o666) を止める
  （sandbox が root なら 0644 で読める。world-writable を残す理由が消える）
- _fix_mount_perms を参照するコメントも一緒に直す

/reset (L720-765): 廃止。PersonaRequest 型は snapshot/restore で再利用するので残す

/snapshot（新設）:
- POST /snapshot {persona}。dependencies=[Depends(_auth)] 必須
- inspect で {{.Id}} と com.nous.sandbox ラベルを確認（他人のコンテナを掴まない）
- コンテナ不在（_missing）は error として扱う
  （snapshot は「実在するマシンの状態保存」なので、なければ作らない）
- docker commit --pause=false <cid> <repo>:<persona>-snap-<UTC timestamp>
  を _call(..., timeout=300.0) で実行。writable layer が数 GB でも 60 秒既定で落ちないように
- repo は要求 image（または SANDBOX_IMAGE）から tag と digest を剥がした repository 部。
  port 付き registry（host:5000/foo）に備え「/ より後ろの最後の :」だけ剥がす。
  ubuntu:24.04 既定なら repo=ubuntu
- timestamp 形式: %Y%m%d-%H%M%S-%f（マイクロ秒）。%f 無しだと同一秒の 2 回目が
  既存タグを黙って上書きするため
- 戻り値: {status, image}。commit 失敗は {status: "error"}
- --pause=false のため commit 中の exec は継続できる。瞬間の整合性は保証しない
  （docs に「DB を抱えた状態の一貫性が欲しいなら自分で止めてから取る」と書く）

/restore（新設）:
- POST /restore {persona, image}。image 必須。_IMAGE_RE で検証
- in_flight チェックは reset と同じ規準に従う（実行中は拒否）
- inspect で {{.Id}} + ラベル確認 → docker rm -f <cid>（ID 指定。
  inspect と rm の間に同名で作り直されても消さない）→ _ensure(persona, image=req.image)
- コンテナ不在で呼ばれたら単に _ensure(image=...)（復元=初回作成も同じ経路）
- snapshot から戻す = image に snap タグを渡す

廃止: SANDBOX_UID / SANDBOX_GID 環境変数（manager・docs・テストから）

### 2. docker/sandbox/Dockerfile

- ARG SANDBOX_UID / ARG SANDBOX_GID / useradd / groupadd / chown -R / USER agent を廃止
- RUN mkdir -p /home/agent/.agents は残す（bind mount の親を Docker が勝手に root 0755 で作るより明示が安全）
- root（uid 0）が既定。/home/agent の WORKDIR は維持

### 3. docs/sandbox.md（大改稿）

- 「コード実行サンドボックス」から「ペルソナ専用マシン」へ冒頭から書き換え
- uid / chown / chmod 777 の節を全削除
- 「コンテナ内 root の制限」節を新設: /proc/sys ro・sysctl 不可・mount/systemctl/iptables 不可・実 VM との違い
- 「既知の帰結」節を新設: wiki/_history 保護は root に無効（自己責任）。
  新規ファイルは root 所有になる（ホスト側 backup / File Station 運用への注意）
- API 表: /reset を削除。/snapshot と /restore を追加（引数・戻り値・--pause=false の整合性注意）
- イメージ更新・復元の手順（token 込み curl の例つき）:
  1. snapshot を取る: curl -X POST .../snapshot -d '{"persona":"herta"}'
  2. /restore に戻したい image を渡す
  3. デプロイ時のワンタイム掃除:
     docker rm -f $(docker ps -aq --filter label=com.nous.sandbox=1)
- デプロイ後の実機チェックリスト（下の検証節と同じ内容を docs にも置く）

### 4. tests/unit/test_sandbox_manager.py

削除・更新:
- fixture の monkeypatch.setattr(sm, "_home_fixed" / "_home_warned", ...)（L71-72）と
  test_in_flight_counts_concurrent_execs 内の同処理を削除（残すと AttributeError）
- reset 関連は 3 本ではなく 8 本 + 認証 assert（L92）。
  L402 / 417 / 460 / 574 / 583 / 592 / 629 / 643 付近を全て洗って 404 検証へ差し替え
- test_fix_mount_perms_opens_rw_mounts_only（L275）を廃止
- L176 の CAP_CHOWN 根拠コメントと L184-188 の 777 assert を削除
- --user の値 0:0 を assert（現行は引数の存在確認のみ）
- --pids-limit と --memory 維持の assert を追加
- 引数に no-new-privileges が「無い」ことの assert を追加

新設:
- /snapshot: 401 / コンテナなし=error / ラベル無し=error /
  commit 引数（--pause=false・タグ形式 %Y%m%d-%H%M%S-%f・repo 導出）/
  timeout=300 / commit 失敗=error
- /restore: 401 / in_flight=拒否 / ラベル無し=拒否 / rm を ID 指定で打つ /
  rm 失敗=error / _ensure に image が渡る / 不在時は ensure のみ
- User 検査: 1026:100 の既存コンテナで warning 1 回（2 回目は出ない）

### 5. 変更しないもの

- sandbox_shell.py / sandbox.py（nous 側）: reset の呼び出し元なし（grep 済み）。/exec は互換。無変更
- _mount_specs のマウント表: 変更なし
- nous 側 wiki store.py の chmod 0666 対策: ローカル実行モードが残るので維持
- manager 自身の cap_drop: ALL / no-new-privileges（compose）: 維持
- compose の manager env: SANDBOX_UID / SANDBOX_GID は元々無し。変更不要

## 検証

1. pytest tests/unit/test_sandbox_manager.py 全緑（上記テスト改訂後）
2. pytest tests/unit/chat/tools/test_sandbox_shell.py 既存緑維持
3. ruff + mypy（baseline を超えない）
4. 実機チェックリスト（デプロイ時。この環境に docker CLI は無いため docs に手順を残す）:
   - docker run --rm <新イメージ> id → uid=0
   - docker inspect -f '{{.Config.User}}' <p>-sandbox 全件
   - apt-get install tree → docker stop → docker start → パッケージが残ること
   - root で touch /home/agent/media/x → EROFS
   - snapshot → restore の往復
   - ls -ln ${DATA_ROOT}/persona/<p>/workspace で新旧の所有者混在を確認

## リスク（了解済み）

- 新規ファイルの所有者が root になる（旧 1026 と混在）。デプロイ時にホスト側 backup 運用を確認
- 旧 1026 コンテナが残る限り _fix_* 削除の影響を被る → ワンタイム掃除をデプロイ手順に強制
- snapshot の commit は --pause=false なので瞬間の整合性は保証しない

## rev3: REVIEW (2026-11-19, ルアン・メェイ) BLOCK の受領と対応

判定: BLOCK。8指摘は解消を確認されたが、唯一の復旧経路 /restore に新たな
競合（B1）が入ったため。指摘と対応:

- **B1 (BLOCKER)**: rm -f → _ensure が _ensure_lock の外。並行 exec に run を
  先に済まされると「復元せずに ok」。→ restore 側で _ensure_lock を取り、
  rm → _ensure_inner 直呼 → .Config.Image の事後検証までをロック内で閉じる
- **B2 (MAJOR)**: restore が in_flight に入らない（idle sweep 競合 / TOCTOU /
  二重 restore）。→ _last_used 先書き + _enter_exclusive（原子な排他入口）で解消
- **B3 (MAJOR)**: docs の image prune が snapshot を消す。→ 明示 docker image rm
  のみ、prune -a 禁止、snapshot は backup の代用でない旨を明記
- **B4 (MAJOR)**: 復旧 curl が compose の expose 構成で実行不能。→
  docker exec nous-sandbox-manager curl 形式に全面書き換え
- **B5 (FYI)**: RestoreRequest.image 必須だと 422 でエンベロープ契約を破る。
  → image: str = "" にして _IMAGE_RE へ一本化
- **B6 (FYI)**: restore が network/memory を引き継がない。→ RestoreRequest に
  2項目追加して _ensure_inner へ渡す
- **B7 (FYI)**: docs の SANDBOX_IMAGE 既定値がコード（ubuntu:24.04）と不一致。
  → docs を「コード既定 ubuntu:24.04 / compose は ghcr.io/... を渡す」へ修正
- **B8 (FYI)**: _image_repo が host:5000/ で空 repo を返す。→ snapshot 側に
  空/末尾スラッシュの1行ガード
- **B9 (FYI)**: 本計画の「ペルソナが HTTP で自分のマシンを守れる」は構造上
  成立しない（exec 中は in_flight で拒否、通れば rm -f が自分を殺す）。
  **計画文言の誤り**。→ docs に「restore は sandbox の外から実行する」と明記。
  運用としては「ペルソナは snapshot まで。restore は運用側（私/人形）が行う」
- **T1〜T5**: B1 検出テスト・timeout の名指し検査・umask 非依存化・env 固定・
  欠落テスト4本

備考: rev2 の逸脱（reset テスト 8本→2箇所への集約）はレビュー時に認定済み。
