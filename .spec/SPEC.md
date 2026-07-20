# SPEC — ディレクトリ構造リファクタリング

## 1. 概要
ペルソナ固有データを `{data_root}/persona/{persona_name}/` に集約し、
Docker コンテナ内のデータルートを `/data` に統一するリファクタリング。

## 2. データルート
- **環境変数**: `NOUS_DATA_ROOT`（変更なし）
- **デフォルト値**: `./data`（変更なし）
- **Docker コンテナ内**: `/opt/nous` → `/data` に変更

## 3. ペルソナディレクトリ構造

### Before
```
{data_root}/memory/{persona_name}/
├── memory.sqlite
├── inventory.sqlite
├── chat.db
├── images/
├── tts_cache/
├── skills/
└── config.json
```

### After
```
{data_root}/persona/{persona_name}/
├── memory.sqlite
├── inventory.sqlite
├── chat.db
├── images/
├── tts_cache/
├── skills/
└── config.json
```

## 4. Settings 変更

| プロパティ | Before | After |
|-----------|--------|-------|
| `data_dir` | `{data_root}/memory` | **廃止** → `persona_dir` に置換 |
| `persona_dir` | (なし) | `{data_root}/persona` |
| `persona_path(name)` | (なし) | `{data_root}/persona/{name}` (新規メソッド) |
| `skills_dir` | `/opt/nous/skills` | `/data/skills` |
| `import_dir` | `{data_root}/import` | 変更なし |
| `cache_dir` | `{data_root}/cache` | 変更なし |
| `config_dir` | `{data_root}/config` | 変更なし |

## 5. 影響ファイル一覧

### Python コード
| # | ファイル | 変更箇所 |
|---|---------|---------|
| 1 | `nous/config/settings.py` | `data_dir` → `persona_dir`/`persona_path()`, `skills_dir` 変更, `ensure_directories()` 更新 |
| 2 | `nous/api/http/routers/persona.py` | `data_dir` → `persona_dir`, 画像パス変更 (L57-58, L70-73, L220-225, L329) |
| 3 | `nous/api/http/routers/chat.py` | 画像URLパス `/memory/images/` → `/persona/images/` (L543) |
| 4 | `nous/api/http/routers/tts.py` | TTSキャッシュパス (L116, L254) |
| 5 | `nous/application/chat/pipeline/prompt.py` | persona_skills_dir (L85-89) |
| 6 | `nous/application/chat/tools/builtin.py` | 画像保存パス (L300-301) |
| 7 | `nous/api/mcp/_tools_skill.py` | persona_skills_dir (L32-34) |
| 8 | `nous/domain/chat_config.py` | `_config_path()` (L462) |
| 9 | `nous/main.py` | HF_HOME パス確認、必要なら更新 |

### Docker / インフラ
| # | ファイル | 変更内容 |
|---|---------|---------|
| 10 | `Dockerfile` | `NOUS_DATA_ROOT=/data`, `HF_HOME=/data/cache/huggingface`, skills COPY先変更 |
| 11 | `docker-compose.yml` | ボリュームマウントコメント更新（実質変更不要、`${DATA_ROOT}:/data` は変わらずマウント先だけ変更） |
| 12 | `docker-compose.dev.yml` | `./data:/data` に変更 |

### ドキュメント
| # | ファイル |
|---|---------|
| 13 | `CLAUDE.md` |
| 14 | `README.md` |
| 15 | `docs/` 配下 |

### データ移行
| # | 項目 |
|---|-----|
| 16 | `data/memory/{persona}/*` → `data/persona/{persona}/*` へ移動 |
| 17 | `data/app/` 削除 |

## 6. 後方互換性
- `data_dir` プロパティは非推奨 (deprecated) とし、`persona_dir` へのエイリアスとして残す（移行期間用）
- 既存のデータ移行スクリプトは不要（ファイル移動のみで済む）
- Qdrant コレクション名は変更なし（`memory_{persona_name}` のまま）

## 7. 検証方針
- `pytest` 実行（特に persona 関連テスト）
- パス参照箇所の grep で取りこぼし確認
- Docker ビルド確認
