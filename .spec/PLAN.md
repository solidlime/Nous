# PLAN — ディレクトリ構造リファクタリング (2026-07-20)

## 目的
- ペルソナ固有データを `persona/` ディレクトリに集約
- Docker データルートを `/opt/nous` → `/data` に変更（ベストプラクティス）
- `data/app/` のゴースト削除

## 新構造
```
{data_root}/                     # /data (Docker) or ./data (local)
├── persona/
│   └── {persona_name}/
│       ├── memory.sqlite
│       ├── inventory.sqlite
│       ├── chat.db
│       ├── images/
│       ├── tts_cache/
│       ├── skills/
│       └── config.json          # 既存、ChatConfigFileRepository
├── cache/                       # 変更なし
├── config/                      # 変更なし
├── import/                      # 変更なし
├── skills/                      # グローバルスキル、変更なし
├── qdrant/                      # 変更なし
├── sandbox/                     # 変更なし
├── sudachi/                     # 変更なし
└── uploads/                     # 変更なし
```

## やること
1. settings.py: data_dir 廃止 → persona_dir 導入
2. 全パス参照箇所の書き換え（~10ファイル）
3. Dockerfile: /opt/nous → /data に変更
4. docker-compose: ボリュームマウント調整
5. data/app/ 削除
6. data/memory/{persona} → data/persona/{persona} データ移行
7. ドキュメント更新
