# MEMORY

## 設計パターン

### 設定のグローバル vs ペルソナ毎の境界線（2026-07-11 学習）
- **Settings (グローバル/env)**: インフラ共有資源 + 公開情報 (DB URL, API endpoint, サーバーバインド等)
- **ChatConfig (per-persona)**: ペルソナの行動選択 + クレデンシャル (enabled フラグ、ペルソナ固有 API キー等)
- **核心**: `enabled` はペルソナの「意志」の領域。グローバル固定は強制。
- 過去事例: `irodori.enabled` / `portrait_gen.enabled` がグローバル固定 → ペルソナ毎設定化（P1+P2 完了）

### フォールバックパターンの鉄則
新機能追加時は「**既存ユーザーへの後方互換**」を常に維持:
- `chat_config.irodori_enabled or ctx.settings.irodori.enabled` の OR フォールバック
- 新カラム追加時は `DEFAULT 0` / `DEFAULT ''` で安全側に倒す
- 旧 Settings のキーは**残す**（CLI からの有効化用）

### per-persona MCP インスタンスの幻想（2026-07-11 学習）
- 別 MCP インスタンスに分ければ完全分離、とは限らない
- OpenSandbox の場合、`sandbox_list()` は単一バックエンドが全 persona の sandbox を返す
- **真の分離は Nous レベルのフィルタリング** または OpenSandbox バックエンドの namespace 対応が必要
- プロセス分離は「障害境界」と「運用上の独立性」には貢献するが、データ分離は限定的

## アーキテクチャの教訓

### 動的 vs 静的なコンテナ管理（2026-07-11 学習）
- Phase B で「init container 方式を棄却、静的 YAML テンプレ（案 B'）採用」→ シンプルだが柔軟性ゼロ
- ユーザーから「動的プロビジョニング + ハードコード廃止」要求 → 案 A (App-level Orchestration) に方針転換
- 教訓: **YAGNI と柔軟性のバランス**。MVP 後に要件が変われば再設計を恐れるな
- 動的プロビジョニングの鉄則: `ensure()` の冪等性 + `_adopt_orphaned()` の障害復旧

### Docker socket 露出の影響評価
- `opensandbox` サービスが既にマウントしている socket を `nous` にも追加することは、**信頼境界の拡張であり、新たな境界を開くわけではない**
- 本番では `tecnativa/docker-socket-proxy` で最小権限化（CONTAINERS=1, POST=1, CONTAINERS_DELETE=1 のみ許可）
- Podman socket も `DOCKER_HOST` env で切り替え可能 → docker-py は docker-compatible

## 失敗パターン

### `import os` のような修正漏れの典型（2026-07-11 学習）
- 症状: ruff check 0 / pytest pass なのに CI (Lint & Format step) が失敗
- 原因: fixer がローカル ruff チェックで `os` 名前解決を検証しなかった（pre-existing だと誤認）
- 教訓: 既存 import リストにない名前を使う場合は **明示的に import 追加** を指示。fixer への指示文に「import の追加を確認」を含める
- CI の Lint & Format step が最終防衛線として機能した（`F821 Undefined name`）

### 既存テストの in-memory DB スキーマ不一致（2026-07-11 学習）
- 症状: 新カラム追加で 8 件の既存テストが一斉失敗
- 原因: `test_chat_service.py:317-372` と `test_compress_step.py:667-721` の `_make_db` ヘルパーが `chat_settings` テーブルをハードコードで作成
- 教訓: 過去 `sandbox_enabled` 削除でも同じ罠 → **新カラム追加時は両方のテストファイルを必ず確認**
- 対策案: `SQLiteConnection._CHAT_SESSIONS_SCHEMA` から動的に生成する helper を導入（リファクタリング案件）

### 大規模依存削除の手順（2026-07-11 学習）
- 依存削除時は以下の順で確認・削除する:
  1. アプリケーションコードの参照（import・関数呼び出し・定数）
  2. スキーマ定義（CREATE TABLE・migration ALTER TABLE）
  3. 設定定義（Settings フィールド・RuntimeConfig SETTINGS_META）
  4. 依存定義（pyproject.toml dependencies）
  5. テストファイルの参照・テストファイル自体の削除
  6. ファイル削除（削除予定ファイルへの import が残っていないか確認）
- **SQL VALUES とカラム数の一致**は手動編集で崩れやすい。`?` placeholder 数とカラム数の一致を必ず確認する（スクリプト検証推奨）
- 削除後は必ず `ruff check nous/ tests/` と `ruff format --check nous/ tests/` の両方を CI と同じ条件で実行

### 環境変数名不一致（2026-07-11 学習）
- 症状: SearXNG URL 解決失敗、ただし health check はなぜか動作
- 原因: `docker-compose.yml` で `SEARXNG_URL` 設定、`RuntimeConfigManager._get_env_key` は `NOUS_SEARXNG_URL` を期待
- 教訓: **設定の読み取りロジックを grep で確認**してから env 名を決定。プレフィックスは settings.py の `env_prefix` を尊重
- 対策: `os.environ.get("SEARXNG_URL", ...)` の fallback を defense in depth として追加

### 本番環境と dev compose の差異（2026-07-11 学習）
- 症状: dev compose で Healthy、本番 compose で起動失敗
- 原因: volume 権限、healthcheck のコマンド存在、pip キャッシュの差
- 教訓: dev compose はソースマウントで多くの問題を隠蔽する → **本番 compose での動作確認は独立して必要**
- 対策: `user: "0:0"` のように権限問題を回避するか、init container で chown する

## 運用ルール

### コミット粒度の指針
- 機能単位（feat / fix / chore）で 1 コミット
- ドキュメント反映（docs:）は別コミット
- 仕様駆動の成果物（`.spec/`）も別コミット
- HANDOFF 更新は別コミット
- 緊急修正（CI 失敗など）は独立コミットで `fix(...)` プレフィックス

### fixer への指示テンプレ（2026-07-11 確立）
1. **背景・設計の最終決定**（Oracle レビュー結果を反映）
2. **採用するアーキテクチャ**（図示）
3. **環境変数**（必須/オプション一覧）
4. **既存コードの重要事実**（get_or_create の挙動など、調査結果）
5. **実装スコープ**（タスク番号、ファイルパス）
6. **TDD 適用**（RED→GREEN→REFACTOR）
7. **検証ゲート**（ruff, pytest, YAML 構文チェック）
8. **テストスコープ制限**（自身の変更ファイルのみ、全テストスイートは orchestrator 責務）
9. **コミット**（コマンド）
10. **報告**（項目リスト）

## ツール別 Tips

### Playwright MCP Docker 起動の罠
- イメージのデフォルト ENTRYPOINT が `["node", "/app/cli.js", "--headless", "--browser", "chromium", "--no-sandbox"]` で `--port` がない
- **stdio モードで起動** → Docker デタッチドでは stdin 即 EOF → exit(0) → restart loop
- 修正: `entrypoint: ["node"]` + `command` で全引数明示 + `--port 8931 --host 0.0.0.0 --allowed-hosts *`
- healthcheck は `/sse` (POST 専用) ではなく **SSE GET** エンドポイントを叩く

### opensandbox の環境変数
- `OPENSANDBOX_INSECURE_SERVER=YES` — 非対話モードで API キー空を許可（必須）
- healthcheck で `python` 不可（Rust 製イメージ）、`wget` か `curl` を使う

### SearXNG URL 解決
- `docker-compose.yml` → `NOUS_SEARXNG_URL` を使う（`SEARXNG_URL` ではない）
- 修正前は `SEARXNG_URL` で設定されていたため、Settings のデフォルト `http://localhost:8080` が使われていた
- `main.py:168-169` の health check だけが `os.environ.get("SEARXNG_URL", ...)` の fallback を持っていた

## 数字で見る Nous

- コミット数（2026-07-11 時点）: main ブランチに 11 コミット
- テスト数: 1646 passed / 7 skipped
- MCP ツール（Nous 内部）: 19 個（うち 5 個は builtin 委譲）
- per-persona MCP インスタンス: 当初 herta/alice/bob の 3 個ハードコード → 動的プロビジョニング化予定
- 設定振り分け問題: 5 件 (P1-P5) のうち P1, P2, P5 完了、P3, P4 は現状維持推奨
