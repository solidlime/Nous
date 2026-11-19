# sandbox を素 ubuntu に戻し、TZ を Nous 設定から引き継ぐ

作成: ヘルタ 2026-11-20
承認: らうらう m01046「まっさらな ubuntu イメージを渡す。全部自由にエージェントに使わせる思想。マウントはそのまま。/etc/timezone を nous 設定から引き継ぎたい」

## 経緯

- 2026-11-17 の `docs/sandbox-requirements-herta.md` は「診断系も焼き込め」を要求し、
  `docker/sandbox/Dockerfile`（python3 / git / curl / ripgrep / 診断系 / tzdata 焼き込み）として実装された。
- #96 で sandbox は root・全永続・専用マシン化された。**道具を焼く理由が消えた**:
  エージェントが root で自由に apt できるから、最初から入れる必要が無い。
- らうらうの 2026-11-20 方針: 「何も tool が入ってないまっさらな ubuntu を渡す。
  全部自由にエージェントに使わせる思想。マウントはそのまま。」
- TZ は現状 `-e TZ=`（compose から `TZ: ${TZ:-Asia/Tokyo}`）を渡すだけ。
  `/etc/timezone` は誰も書かないため、`/etc/timezone` を読む物は Etc/UTC 扱いになる
  （requirements §3 の「静かに壊れる箇所」の1つ）。Nous 設定の `Settings.timezone`
  （既定 Asia/Tokyo, env `NOUS_TIMEZONE`）と sandbox の TZ が繋がっていない。

## 変更 A: 素 ubuntu イメージ化（まっさら）

1. `docker-compose.yml` の manager environment:
   `SANDBOX_IMAGE: ${SANDBOX_IMAGE:-ghcr.io/solidlime/nous-sandbox:latest}`
   → `${SANDBOX_IMAGE:-ubuntu:24.04}`（コード既定に揃う）。
2. `docker/sandbox/Dockerfile` を削除。
3. `.github/workflows/docker.yml` から `build-sandbox` job と `SANDBOX_IMAGE_NAME` env を削除。
4. `docs/sandbox-requirements-herta.md` に撤回ブロックを追記
   （本書の焼き込み要求は #96 root 専用マシン化で前提が変わり撤回。TZ 要望は本書 §3 が起源）。
5. `docs/sandbox.md` の SANDBOX_IMAGE 行・思想を更新。

マウント（`_mount_specs`）は**無変更**（らうらう指定どおり）。
`SANDBOX_APT_EXTRA`（オプトインの差分インストール）は思想と矛盾しないので残す。

## 変更 B: TZ を Nous 設定から引き継ぐ

1. `nous/services/sandbox_manager.py` に `_tz()` を追加:
   `SANDBOX_TZ` env（個別上書き）→ `get_settings().timezone`（= `NOUS_TIMEZONE` env / .env）→ `"UTC"`。
   `get_settings` の import は `_tz()` 内（循環回避・起動コスト）。
2. run 時の `-e TZ=`（:488）を `_tz()` 由来にする（親プロセスの `TZ` env は参照しなくなる）。
3. `_apply_timezone(zone)` を追加し、`_post_run` の**冒頭**で呼ぶ:
   ```
   [ -f "/usr/share/zoneinfo/{zone}" ] && printf '%s\n' "{zone}" > /etc/timezone && ln -sf "/usr/share/zoneinfo/{zone}" /etc/localtime
   ```
   - 実装では `_tz()` で検証済みの zone を Python 側で `{zone}` 直接埋め込み（上の例の `$TZ` env 参照は採用しない — 埋め込み値が単一 sink に閉じるように）。
   - run 直後の新規コンテナにのみ適用（restart 経路には入れない — エージェントが変えた
     /etc/timezone は尊重する。冪等で多少の再実行は無害だが、思想上「作成時に一度」）。
   - `bash -lc` で実行、失敗は**警告のみ**（run を殺さない — `_install_missing` と同じ方針）。
   - DNS チェックより前に実行（DNS 失敗コンテナにも tz が付くように）。
   - 素 ubuntu:24.04 には tzdata が含まれる（zoneinfo 一式）。万一無ければ `[ -f ]` が
     silent skip し、警告ログだけ残る。素 ubuntu で `/etc/localtime` が無いと `date` 自体が
     動かないため tzdata は必須パッケージ扱いで base に入っている。
4. `:489` の git identity コメントを修正（素 ubuntu には git が無い。GIT_AUTHOR_* env は
   エージェントが git を入れた後の commit identity 用）。

## 変更 C: compose と docs

1. `docker-compose.yml` manager environment に `NOUS_TIMEZONE: ${NOUS_TIMEZONE:-Asia/Tokyo}` を追加。
   Nous 本体と同じ env 変数で sandbox の TZ も決まる（設定が1本化される）。
   既存の `TZ: ${TZ:-Asia/Tokyo}` は manager プロセス自身の logger 用に残す。
2. `docs/sandbox.md`:
   - 環境変数表の `SANDBOX_TZ` 行: 既定を「Nous 設定の `timezone`（`NOUS_TIMEZONE`、既定 Asia/Tokyo）」に更新。
   - `NOUS_TIMEZONE` 行を追加。
   - `SANDBOX_IMAGE` 行: compose 既定が ubuntu:24.04 になった旨。
   - 既存稼働コンテナへの tz 後付け手順（運用側が 1 回だけ実行）:
     ```
     docker exec <persona>-sandbox bash -c '[ -f /usr/share/zoneinfo/Asia/Tokyo ] && printf "Asia/Tokyo\n" > /etc/timezone && ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime'
     ```

## テスト計画（tests/unit/test_sandbox_manager.py）

1. `_tz()` 優先順位 3 本:
   - `SANDBOX_TZ=Europe/Berlin` → Europe/Berlin（settings を読まない）
   - 未設定 + `NOUS_TIMEZONE=Europe/Berlin` + `get_settings.cache_clear()` → Europe/Berlin
   - 未設定 + `NOUS_TIMEZONE` delenv + cache_clear → 既定 Asia/Tokyo
2. run 時の `-e TZ=` が `_tz()` 由来（既存 `test_run_inherits_the_parent_tz_and_forces_utf8` を
   改名・修正: 親 TZ は継承しない。`TZ=UTC` でも settings の Asia/Tokyo が勝つ、を検証）。
3. `_apply_timezone`:
   - `_post_run` 冒頭で exec が飛ぶ（引数に `/etc/timezone` 書き込みを含む）
   - DNS チェックより**前**に飛ぶ（calls 順序）
   - exec 失敗（exit 2）でも ensure は成功（run を殺さない）
4. 検証: `.venv/bin/pytest tests/unit/test_sandbox_manager.py` → 全体 pytest → ruff → mypy（対象ファイル）→ docs drift。

## 影響とリスク

- 既存稼働コンテナは旧イメージのまま動く（イメージは作成時固定）。素 ubuntu に作り直すかは
  らうらうの判断。tz 後付けは docs の手順で 1 回実行。
- snapshot/restore は `commit` したイメージに戻るため、素 ubuntu 化の影響を受けない。
- ghcr.io/solidlime/nous-sandbox は以後ビルドされない（パッケージ自体は GHCR に残る）。

## 進行

- [x] EXPLORE
- [x] PLAN（本書）
- [x] IMPLEMENT（直実装 — 規模小・全ファイル把握済み）
- [x] TEST
- [x] REVIEW（ルアン・メェイ: 1回目 BLOCK 10件 → 対応 → 2回目 BLOCK 6件 → 対応 → 3回目依頼）
- [ ] GATE（pytest 全緑 + ruff + mypy + docs drift）
- [ ] COMMIT
- [ ] RECORD
