# Nous をハーネス化する計画

## Context

ユーザーは Muse / OpenMuse 型のエージェントハーネスを自作したいと考えている（外部製品は「しっくりこない」）。
移植したいのは UI ではなく、**Nous のチャット機能を拡張して「手・統制・記録・分業」を持たせる**こと。
とくに不満の中心は**コンテキスト管理（記憶の汚染）**で、長い会話やツール出力が文脈を壊さない仕組みが要る。

Nous は既に「ペルソナ・記憶・スキル・MCP・多段パイプライン」を持つ。足りないのは:

| 層 | 現状 | 足すもの |
|---|---|---|
| 手 | 記憶系ツールのみ | シェル・ファイル読み書き |
| 統制 | なし | ワークスペース境界・承認 |
| 記録 | `tool.called` のみ | コマンド・exit code・成果物パス |
| 分業 | なし | サブエージェント（後続） |

MVP は **WebUI チャットからシェルを叩ける**ところまで。承認 UI とサブエージェントは次フェーズ。

## 現状の土台（新規に作らない）

- `nous/application/chat/tools/registry.py` — `ToolRegistry`。builtin/MCP をルーティングし、成功・失敗どちらでも `tool.called` をイベントバスへ publish する。`defer_loading` による段階開示（`search_tools`）も既存。
- `nous/application/chat/tools/definitions.py:345` `get_filtered_tools(config)` — `CORE_ALWAYS_TOOLS` 以外を `dynamic_tool_selection` / `disabled_tools` で篩う。ツール追加はここに定義を足すだけで通る。
- `nous/application/chat/tools/builtin.py:429` `execute_tool` → `_BUILTIN_DISPATCH[tool_name]`。`:90` `truncate_tool_result` は既存の切り詰め機構。
- `nous/application/chat/pipeline/inference.py:81` の while ループと `:391` `_execute_pending_tools` — ツール実行はここに集約。`enable_parallel_tools` で並列化済み。
- `nous/infrastructure/sqlite/session_event_repo.py` + `GET /api/session-events/{persona}` — `tool.called` を既にクエリできる＝監査台帳の土台はある。
- `nous/application/chat/turn_hub.py` — ターン実行中フラグとキャンセル。承認待ちも同じ `asyncio.Event` パターンで載る。
- `nous/config/settings.py:447` `data_root` → `{data_root}/persona/{persona}/...`。

## Approach

### 1. 手 — ワークスペースツール（今回）

`ToolConfig.workspace_root` を唯一の境界にする。未設定ならツール自体を登録しない（＝オプトイン）。

追加するツールは 4 つだけ。`grep` / `glob` は `bash` で足りるので作らない。

- `bash(command, timeout_seconds?)` — `workspace_root` を cwd に実行
- `read_file(path, offset?, limit?)` — ワークスペース相対パスのみ
- `write_file(path, content)` — 親ディレクトリは作る
- `edit_file(path, old_text, new_text)` — 完全一致 1 箇所のみ。曖昧ならエラーで返す（モデルに読み直させる）

**境界の実装**は `Path.resolve()` 後に `workspace_root` で prefix 判定。symlink も resolve で潰れるので、これで `../../etc/passwd` も外への symlink も弾ける。`workspace_root` 自体も起動時に resolve して保持する。

**コンテキスト衛生**（最重要不満への直接の回答）:

- `bash` の返り値は `{exit_code, stdout_tail, stderr_tail, truncated, log_path}` の**末尾 120 行だけ**。全文は `{data_root}/persona/{persona}/artifacts/{session_id}/{ts}-bash.log` に落とし、必要ならモデルが `read_file` で読み直す。
- `read_file` は 2000 行 / 50KB で切って `offset` を案内する（既存 `truncate_tool_result` の思想を踏襲）。
- これにより「巨大ログが会話履歴に焼き付く」経路が消える。既存の `compress` / `trimmer` パイプラインはそのまま生きる。

### 2. 統制 — 承認とサンドボックス（Phase 2）

`ToolConfig.shell_approval_mode` を `"auto" | "allowlist" | "ask"` で持つ。既定 `"ask"`。

- `ask`: `write_file` / `edit_file` / `bash` の実行前に `approval.requested` を SSE で流し、`asyncio.Event` で待つ。UI は `POST /api/chat/{persona}/approval` に `{approval_id, decision, remember}` を返す。120 秒で自動 deny。
- `allowlist`: `shell_allowed_commands` に載るコマンドの先頭トークンだけ無承認で通す。
- `auto`: 全通し（ワークスペース境界は維持）。

承認待ちは `turn_hub.py` に `pending_approvals` を足すのが最小（既存のキャンセルと同型）。`inference.py._execute_pending_tools` の手前で止める。

### 3. 記録 — 監査ログ（Phase 1 に前倒し・小さい）

`ToolRegistry.execute` が publish する `tool.called` の payload に `command` / `exit_code` / `duration_ms` / `paths` を足すだけ。新しいログ基盤は作らない。`GET /api/session-events/{persona}?event_type=tool.called` でそのまま引ける。

リプレイ UI は Phase 4。まず「後から grep できる」を満たす。

### 3.5 コンテキスト衛生 — 「記憶の汚染」への回答（Phase 3）

Nous には既に `memory_retriever.py`（検索）/ `compress.py` / `trimmer.py` / `summarizer.py` がある。汚染が残る経路は 3 つで、それぞれ手当てが違う。

| 経路 | 何が起きる | 手当て |
|---|---|---|
| ツール出力 | 巨大ログが履歴に焼き付く | `bash` / `read_file` の末尾返し + artifact 化（Phase 1） |
| 記憶検索の誤爆 | 無関係な記憶が文脈を薄める | 検索結果にスコアを付け、閾値未満は注入しない。既存 `memory_retriever` のスコアを `prepare.py` 側で篩う |
| 要約の累積 | 圧縮の要約が積み重なり、原文が失われる | `compress` の要約に artifact パスを必ず含める（原文へ戻れる導線を残す） |

設計原則は 1 つ: **コンテキストには「索引」だけを置き、本体はファイルに置く**。Muse の JSONL ログと同じ発想で、モデルは必要なとき `read_file` で取りに行く。

### 4. 分業 — サブエージェント（Phase 4）

専用基盤を作らず、`delegate(agent, prompt, workdir?)` 1 ツールで `pi --print` を subprocess 起動する。cwd はワークスペース、出力は bash と同じ末尾 N 行 + ログパス。`enable_parallel_tools` が既にあるので、複数 `delegate` 呼び出しは自然に並列になる。

`pi` の呼び出しは承認モードに従わせ、`delegate` 自体も `tool.called` に載せる。

## Files to modify

新規:
- `nous/application/chat/tools/workspace.py` — `resolve_workspace(config)` / `resolve_in_workspace(root, path)` / `artifact_path(...)`
- `nous/application/chat/tools/shell.py` — `_handle_bash` / `_handle_read_file` / `_handle_write_file` / `_handle_edit_file`
- `tests/unit/chat/tools/test_shell.py` — 境界突破・切り詰め・edit の曖昧一致

変更:
- `nous/domain/tool_config.py` — `workspace_root: str = ""`, `shell_timeout_seconds: int = 120`, `shell_approval_mode: str = "ask"`, `shell_allowed_commands: list[str] = []`
- `nous/application/chat/tools/definitions.py` — `WORKSPACE_TOOLS` を追加し、`get_filtered_tools` で `workspace_root` 未設定時に除外
- `nous/application/chat/tools/builtin.py` — `_BUILTIN_DISPATCH` に 4 ハンドラ登録、`tool.called` payload 拡張
- `nous/api/http/routers/chat/chat_management.py:104` 付近の設定マッピング — 新フィールドを `tools` セクションに通す

Phase 2 以降:
- `nous/application/chat/turn_hub.py` / `nous/api/http/routers/chat/chat_stream.py` / `nous/application/chat/pipeline/inference.py:391` / `nous/api/http/static/chat/*.js`

## Reuse

- ツール定義: `ToolDefinition`（`nous/infrastructure/llm/base.py`）と `definitions.py` の書き方
- 実行: `_BUILTIN_DISPATCH` / `execute_tool`（`nous/application/chat/tools/builtin.py:429`）
- 切り詰め: `truncate_tool_result`（`builtin.py:90`）の思想を `shell.py` 内で踏襲
- イベント: `ctx.event_bus.publish("tool.called", ...)`（`registry.py`）
- 設定: `ToolConfig`（`nous/domain/tool_config.py`）
- パス: `Settings.data_root` / `persona_path()`（`nous/config/settings.py:447-518`）

## Steps

実装済み（2026-11-17 に実測で確認。チェックはコードの存在で付けた。計画から配置や
実現方法が変わった点は各行に併記）。

### Phase 1（workspace ツール）

- [x] `ToolConfig` に 4 フィールド追加（`nous/domain/tool_config.py:22-34`、既定は無効）
- [x] `workspace.py` — root 解決と境界判定（`nous/application/chat/tools/workspace.py`）
- [x] `shell.py` — 4 ハンドラ（`nous/application/chat/tools/shell.py:114-228`。`bash` は
      `asyncio.create_subprocess_shell` + タイムアウト、出力は末尾のみ + `_save_log`）
- [x] `definitions.py` — `WORKSPACE_TOOLS`（`:385`）。`get_filtered_tools`（`:356`）が
      `workspace_root` 未設定時に除外する
- [x] `builtin.py` — dispatch 登録（`:427`）。監査 payload は `registry.execute` が
      `result["audit"]` を `payload.update(audit)` で取り込む形に変わった
- [x] `chat_management.py` — 設定 API のマッピング（`:111-114`, `:177-180`）
- [x] テスト — 計画の `tests/unit/chat/tools/test_shell.py` ではなく
      **`tests/unit/test_workspace_tools.py`** に置いた（21 テスト。境界・symlink 脱出・
      offset・切り詰め・edit の曖昧一致）

### Phase 2（承認）

- [x] ポリシーを `nous/application/chat/tools/approval.py` に分離。
      `APPROVAL_REQUIRED_TOOLS = {bash, write_file, edit_file, delegate}`、
      `APPROVAL_TIMEOUT_SECONDS = 120.0`、未知モードは ask 扱い（安全側）
- [x] `turn_hub.py` に `pending_approvals` と `resolve_approval`（`:127-140`）
- [x] `inference.py` の手前で承認待ち
- [x] `POST /api/chat/{persona}/approval`（`nous/api/http/routers/chat/chat_stream.py:186`）
- [x] フロントの承認カード（`nous/api/http/static/chat/send/turn.js:178` の
      `approval_requested`）

### Phase 3（コンテキスト衛生）

- [x] 閾値超えの artifact 化 — 計画の `output_bytes` 判定ではなく、`tool_result_max_chars`
      を超えたら `registry._save_artifact` が原文を落とす形（`registry.py:35-51`）
- [x] 圧縮時にログパスだけ残す — `pipeline/trimmer.py:159` の `_ARTIFACT_REF_RE` が
      `artifact_path` / `log_path` を参照として残す
- [x] 記憶検索の誤爆 — `memory_min_score`（`nous/domain/chat_config.py:84`）を
      `pipeline/prepare.py:234,301` で足切り

### Phase 4（分業・リプレイ）

- [x] `delegate` ツール（`nous/application/chat/tools/delegate.py`、`definitions.py:453`、
      `builtin.py:427`）
- [x] ツール実行の一覧 — 専用タイムライン UI は作らず、既存 Activity 画面の
      `event_type=tool.called` フィルタで読む（`nous/api/http/sections/activity.py:172`）

## 残件

なし。計画の全項目が実装済みで、テスト（`tests/unit/test_workspace_tools.py`）と
既存の統合テストが常設で守っている。

未検証なのは Verification の「手動」項目だけで、これは実機で `workspace_root` を
設定して `bash` を呼ぶまで確認できない。実装の穴ではなく、運用手順の未実行。

## Verification

- `pytest tests/unit/chat/tools/test_shell.py -q`
- 手動: WebUI でペルソナの設定 `workspace_root` を `/root/workspace/Nous` にしてから「`git status` を見て」→ ツールが `bash` を呼び、SSE に `tool.called` が出て、`ls` の結果が末尾だけ返ることを確認
- 境界: `read_file("../../etc/passwd")` が `status: error` で返る
- 巨大出力: `seq 1 100000` を `bash` に投げ、返り値が末尾 120 行 + `log_path` だけであること
- 監査: `GET /api/session-events/{persona}?event_type=tool.called` に `command` と `exit_code` が載っていること
- `ruff check` / `pyright`（プロジェクト既定の品質ゲート）
