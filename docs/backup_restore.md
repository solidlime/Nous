# バックアップ / リストア / ポータブルエクスポート

実装: `scripts/backup_restore.py`（stdlib のみで動作。Qdrant の復元だけ任意で `qdrant-client` を使う）。
方針: **wiki(ファイル) が正本、SQLite は状態、Qdrant はその索引**（Zero Inbox 以降、編纂済み知識は
`persona/<p>/wiki/*.md` にあり、編纂された生記憶は SQLite から物理削除される）。

---

## 1. 何が正本か（バックアップの優先順位）

| 層 | 場所 | 中身 | 正本性 | 失った場合 |
|----|------|------|--------|-----------|
| wiki | `<DATA_ROOT>/persona/<persona>/wiki/**.md` | 編纂済み知識・日記・未解決の問い・`_purged/*.jsonl`（退避 gist） | **正本** | 復元不能（最重要） |
| SQLite | `<DATA_ROOT>/persona/<persona>/memory.sqlite` | 未編纂の生記憶・強度・ブロック・感情履歴・日記材料（`session_events`）・未解決質問・goal/promise | 状態 | 生記憶の受信トレイが消える |
| SQLite | `<DATA_ROOT>/persona/<persona>/inventory.sqlite` | 所持品・装備・装備履歴 | 状態 | 持ち物が消える |
| 設定 | `<DATA_ROOT>/config/config_overrides.json` | WebUI で保存した設定（**API キーを含む**） | 状態 | 既定値に戻る（`.env` は別管理） |
| Qdrant | `<DATA_ROOT>/qdrant/`（volume） | `memory_<persona>` / `wiki_<persona>` のベクトル | **派生物（キャッシュ）** | 意味検索が弱る。再構築可能（下記 §6） |

`<DATA_ROOT>` は docker compose なら `.env` の `DATA_ROOT`（既定 `./data`、コンテナ内は `/data`）。

### バックアップに含めないもの

`data/cache/`（HuggingFace モデル）、`data/logs/`、`data/sudachi/`（207MB の辞書）、
`data/qdrant/` の**生コピー**（稼働中コピーは RocksDB の不整合を招くので snapshot API を使う）、
`node_modules/`、`data/hub.db`（コード参照ゼロの残骸）。manifest の `excluded` に理由つきで記録される。

---

## 2. 整合バックアップ（オンライン実行可）

```bash
# repo ルートで
python3 scripts/backup_restore.py backup --data-root ./data --out ./backups
# Windows (PowerShell)
py -3 scripts\backup_restore.py backup --data-root D:\Code\Nous\data --out E:\NousBackups
```

処理内容と整合性の担保:

1. **SQLite**: `sqlite3.Connection.backup()`（オンラインバックアップ API）。WAL 有効・書き込み中でも
   単一トランザクション相当の一貫した複製が取れる。複製後に `PRAGMA journal_mode=DELETE` で WAL を
   畳み、`PRAGMA integrity_check` と主要テーブルの行数を manifest に記録。
2. **wiki**: ファイル単位でコピー。`WikiStore.write_page()` は `tmp + os.replace` の原子的書き込み
   なので、稼働中でも半端なページを掴まない。各ファイルの sha256 を manifest に記録。
3. **config**: `config_overrides.json` をコピー（`--no-config` で除外）。**API キーを含む**ので
   共有・クラウド保存するなら `--no-config` を使う。
4. **Qdrant**: collection ごとに `POST /collections/{name}/snapshots?wait=true` でサーバ側 snapshot を
   作成 → ダウンロード → サーバ側 snapshot を削除（ディスクを食い潰さない）。`memory_<p>` と
   `wiki_<p>` のみ対象。Qdrant に到達できない場合は警告して wiki/SQLite だけで完了する
   （終了コード 2 = 部分バックアップ。`--allow-partial` で 0 に、`--require-qdrant` 相当の厳格化は
   CI では終了コード 2 を失敗扱いにすればよい）。

生成物:

```
backups/nous-backup-YYYYMMDD-HHMMSS/
├── manifest.json                      # sha256・行数・integrity・qdrant 情報・除外理由
├── sqlite/<persona>/{memory,inventory}.sqlite
├── wiki/<persona>/**.md               # index.md / _purged/*.jsonl も含む
├── config/config_overrides.json       # --no-config で無し
└── qdrant/{memory_,wiki_}<persona>.snapshot
```

オプション: `--persona <name>`（複数可、既定は `memory.sqlite` を持つ全ペルソナ）、
`--qdrant-url` / `--qdrant-api-key`（既定は `NOUS_QDRANT__URL` か `http://localhost:6333`）、
`--no-qdrant`。

### 検証

```bash
python3 scripts/backup_restore.py verify --backup ./backups/nous-backup-20261115-021527
```

manifest の全ハッシュを再計算し、各 SQLite に `integrity_check` をかける。1 つでも食い違えば
終了コード 1。**バックアップ直後に自動で走る**ので、ディスク不良やコピー漏れはその場で分かる。

---

## 3. リストア

> 稼働中の復元は禁止。SQLite のファイル差し替えは WAL と衝突する。
> `docker compose stop nous`（Qdrant は `--with-qdrant` を使うときだけ起動したまま）。

```bash
docker compose stop nous

# wiki + SQLite（+ 設定）を戻す。既存データは persona/<p>/_pre_restore_<ts>/ へ退避される
python3 scripts/backup_restore.py restore \
    --backup ./backups/nous-backup-20261115-021527 \
    --data-root ./data --force

# ベクトルも戻す場合（qdrant-client が必要。無い場合は手動 curl コマンドを表示して中止）
python3 scripts/backup_restore.py restore --backup ./backups/nous-backup-... \
    --data-root ./data --force --with-qdrant --with-config

docker compose up -d nous
```

挙動:

- `--force` なしで既存ファイルがあると**何も壊さずに拒否**する（衝突パスを列挙）。
- `--force` は削除ではなく `_pre_restore_<ts>/` への**退避**（`memory.sqlite` の `-wal`/`-shm` も一緒に退避）。
- `--with-qdrant` は `POST /collections/{name}/snapshots/upload?priority=snapshot` 相当で
  既存 collection を上書きする。`--persona` で対象を絞れる。
- `--with-config` を付けない限り設定は触らない（復元先の API キーを巻き戻さないため）。

### 復元後の確認

1. `curl -s localhost:26262/health`
2. WebUI で wiki 一覧・記憶一覧の件数が manifest の `rows` と一致するか
3. 検索スモーク（既知のクエリで 1 件以上ヒットするか）— 意味検索が空なら `--with-qdrant` を
   使っていない可能性が高い（§6）
4. 問題なければ `_pre_restore_<ts>/` を削除

---

## 4. ポータブルエクスポート方針

目的: **Nous を別ホストへ引っ越す / 人に渡す / 长期保管する**。バックアップとの違いは
「秘密を含めない」「実行環境（ベクトル・DB ファイル形式）に依存しない」こと。

```bash
python3 scripts/backup_restore.py export --data-root ./data --out ./nous-portable.zip
```

中身:

| エントリ | 内容 | 理由 |
|---------|------|------|
| `wiki/<persona>/**.md` | 編纂済み知識（正本） | Zero Inbox 後は「wiki があれば知識は移る」 |
| `memories/<persona>.jsonl` | 未編纂の生記憶ほか全テーブル（既存 `JSONLExporter` を再利用） | wiki に入っていない受信トレイ分だけを可搬形式で運ぶ |
| `config/config_overrides.redacted.json` | 設定（`api_key`/`token`/`password`/`secret` は `***redacted***`） | 環境差分の把握用。秘密は運ばない |
| `manifest.json` | 形式版・作成時刻・ページ数/レコード数・sha256・埋め込みモデルと次元 | 再構築に必要な同一性情報 |

含めないもの: **Qdrant のベクトル**（派生物）、SQLite ファイルそのもの（スキーマ版に依存）、
`data/cache`・`data/logs`・`data/sudachi`。

### ポータブル成果物からの復元（手順）

```bash
unzip nous-portable.zip -d ./portable
# 1) wiki（正本）を置く
mkdir -p $DATA_ROOT/persona/herta
cp -r ./portable/wiki/herta $DATA_ROOT/persona/herta/wiki
# 2) 未編纂の生記憶を入れる（既存 CLI。JSONL は idempotent な upsert）
NOUS_DATA_ROOT=$DATA_ROOT python -m nous.cli import --persona herta --input ./portable/memories/herta.jsonl
# 3) 起動して /health と wiki を確認
docker compose up -d
```

インポートは**ベクトルを作らない**（`nous.cli import` は SQLite のみ）。意味検索を効かせたい場合は
§6 の再インデックスを通す。キーワード検索（FTS）はインポート直後から効く。

---

## 5. 定期実行と保持

```bash
# cron（毎日 03:30、wiki 編纂 03:00 の直後を避けるなら 04:30 など）
30 4 * * * cd /path/to/Nous && .venv/bin/python scripts/backup_restore.py backup --out /path/backups >> /path/backups/cron.log 2>&1
```

Windows タスク スケジューラ: プログラム `py`、引数 `-3 D:\Code\Nous\scripts\backup_restore.py backup
--data-root D:\Code\Nous\data --out E:\NousBackups`。

保持（30 日より古いものを削除）:

```bash
find /path/backups -maxdepth 1 -name 'nous-backup-*' -mtime +30 -exec rm -rf {} +
# PowerShell
Get-ChildItem E:\NousBackups -Directory | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Recurse -Force
```

推奨: 直近 7 日分 + 月初 1 本を別ディスク/NAS へ。`verify` はバックアップ内で自動実行されるが、
長期保管分は月 1 回 `verify` を回す。

---

## 6. 既知の制約（設計上の割り切り）

1. **ベクトルの全件再インデックス CLI は未実装**。`QdrantVectorStore.reencode_stale()` は
   fingerprint が古い point を再エンコードするだけで、空 collection は埋めない。したがって
   「SQLite + wiki だけ復元した状態」では意味検索が欠ける（FTS と recency は動く）。
   現状の完全復元は **Qdrant snapshot を併用**する（`--with-qdrant` / バックアップ既定で取得）。
   全件再エンコードの正規入口が欲しくなったら、起動時の `_start_embedding_migration`
   （`nous/application/context/vector_stack.py`）と同じ経路で「collection を作り直して
   `upsert_batch` で全記憶を流す」CLI を追加するのが素直（未着手）。
2. **SQLite 2 ファイル間は原子的でない**。`memory.sqlite` と `inventory.sqlite` はそれぞれ一貫だが、
   両者の同時点は保証しない（数秒ずれ得る。更新頻度が低いので実害は小さい）。
3. **wiki 全体も瞬間スナップショットではない**。ページ単位では原子的だが、編纂中に取ると
   `index.md` とページ集合が一時的にずれ得る。`index.md` は `WikiStore.rebuild_index()` で再生成
   できるので実害はない。
4. **`--with-config` は API キーを巻き戻す**。復元先の `.env` と `general.api_key` の二重管理に注意
   （`.env.example` の「Recovery」節と同じ手順で片付く）。
5. **Qdrant の生データをコピーしない**。`data/qdrant/` を `cp -r` しても整合は保証されない。
   snapshot API（本スクリプト）か、Qdrant 停止後のコピーだけが安全。

---

## 7. トラブルシュート

| 症状 | 原因 / 対処 |
|------|------------|
| `backup` が終了コード 2 | Qdrant に到達できず snapshot 抜き。`--qdrant-url` を確認（compose 内は `http://qdrant:6333`、ホストからは `http://localhost:6333`） |
| `verify` が sha256 mismatch | コピー中に破損 or 改竄。そのバックアップは捨てて取り直す |
| `restore` が「既存データがある」 | `--force`（退避してから置換）。退避先は `persona/<p>/_pre_restore_<ts>/` |
| 復元後、記憶一覧が空 | `--data-root` の取り違え（compose は `/data`、ホストは `./data`） |
| 復元後、意味検索だけ空 | Qdrant を戻していない（§6-1） |
| `export` が `nous` を import できない | リポジトリの venv で実行する（`JSONLExporter` を再利用するため）。`backup`/`verify`/`restore` は stdlib のみで動く |
