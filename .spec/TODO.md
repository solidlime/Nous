# TODO — ディレクトリ構造リファクタリング

## フェーズ1: コア設定変更
- [x] `nous/config/settings.py` — `persona_dir`, `persona_path()` 追加, `data_dir` 非推奨化, `skills_dir` 変更, `ensure_directories()` 更新
- [x] `nous/config/runtime_config.py` — `"data_dir"` → `"persona_dir"` in SETTINGS_META (Oracle指摘)
- [x] `nous/infrastructure/sqlite/connection.py` — docstring更新, `data_dir`パラメータの意味を明確化 (Oracle指摘)

## フェーズ2: パス参照書き換え（並列可能）
- [x] `nous/api/http/routers/persona.py` — data_dir → persona_dir, 画像パス
- [x] `nous/api/http/routers/chat.py` — 画像URLパス変更
- [x] `nous/api/http/routers/tts.py` — TTSキャッシュパス
- [x] `nous/api/mcp/_tools_skill.py` — persona_skills_dir
- [x] `nous/application/chat/pipeline/prompt.py` — persona_skills_dir
- [x] `nous/application/chat/tools/builtin.py` — 画像保存パス
- [x] `nous/domain/chat_config.py` — _config_path()
- [x] `nous/main.py` — HF_HOME パス確認（変更不要）
- [x] `nous/application/use_cases.py` — data_dir → persona_dir (Oracle指摘)
- [x] `nous/application/auto_import.py` — data_dir → persona_dir (Oracle指摘)
- [x] `nous/cli/__main__.py` — 3箇所 data_dir → persona_dir (Oracle指摘)
- [x] `nous/api/http/routers/admin.py` — data_dir → persona_dir (Oracle指摘)

## フェーズ3: Docker / インフラ
- [x] `Dockerfile` — NOUS_DATA_ROOT=/data, HF_HOME, skills COPY先
- [x] `docker-compose.yml` — マウントパス更新
- [x] `docker-compose.dev.yml` — ./data:/opt/nous → ./data:/data

## フェーズ4: データ移行・クリーンアップ
- [x] `data/memory/{persona}/*` → `data/persona/{persona}/*` 移動（6ペルソナ）
- [x] `data/memory/` 空ディレクトリ削除
- [x] `data/app/` 削除（root-ownedファイル残存）

## フェーズ5: ドキュメント
- [x] CLAUDE.md パス更新
- [x] docs/sandbox.md `data/memory/` → `data/persona/`
- [x] docs/superpowers/plans/2026-06-27-single-sandbox-container.md パス更新（4箇所）
- [x] README.md — 修正不要（パス参照なし）

## フェーズ6: 検証
- [x] grep `data_dir` `memory/` 参照漏れ確認（nous/ 配下）
- [x] Frontend JS/HTML — 変更不要
- [x] test_settings.py 15 passed
- [x] 全体テスト: 269 passed, 1 failed (既存のtest_compress_step.py、今回の変更とは無関係)
