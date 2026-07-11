# HANDOFF — 2026-07-11 09:35

## セッション概要
feat/browser-sandbox-mcp を main にマージ後、3 つのクリーンアップを完結：
(1) WebUI サンドボックス残骸 26 箇所の整理、(2) pytest OOM 修正、(3) CI で顕在化した portrait service の時間依存バグ修正。
合計 4 コミットを main に push（CI 通過確認中）。

## 作業ブランチ
- main（feat/browser-sandbox-mcp の worktree は `.worktrees/browser-sandbox-mcp/` に残存）

## 完了したこと

### 1. main マージ + 既存バグ修正
- `git merge --no-ff origin/feat/browser-sandbox-mcp` → 9 コミット統合
- `.env` から `NOUS_SANDBOX__ENABLED=true` 削除（gitignore 対象、ローカル限定）
- `tests/integration/test_dashboard_e2e.py:238` の version assert を `2.0.0` → `3.0.0` に修正（branding commit `4af063b` の更新漏れ）

### 2. Ruff format 不整合修正（14 files）
- 既存 main に format drift：CI の `ruff format --check` gate を通すため reformat
- 削除: `tests/unit/test_chat_tab_renders_artifacts_tab`（coding_agent.py 削除に伴う）

### 3. pytest OOM 修正（`d83eebf`）
- 主因: `nous/domain/memory/__init__.py:10` の `from ...sudachi_extractor import ...` eager import
  → pytest collection 時に SudachiPy 辞書 (~200MB) をロード
- 副因: `tests/unit/test_read_pdf.py:16` の `import fitz` (PyMuPDF ~100-150MB)
- 修正:
  - `__init__.py` の `__getattr__` 実装で遅延化
  - `test_read_pdf.py` の `import fitz` を9つのテスト関数内に移動
- 結果: フルテストスイート 1605 passed / 7 skipped / 488 秒（OOM 解消）

### 4. WebUI サンドボックス残骸整理（`0aa3b90`）
explorer 調査で 26 箇所の sandbox 残骸（coding_agent.js / chat.js / settings.js）と animateCount の残存を検出。
oracle の設計判断で 9 タスクに分解し、3 fixer 並列実行：

| タスク | 担当 | 結果 |
|---|---|---|
| P0-1: `execute_tool()` に `__` MCP ルーティング追加 | fixer A | 完了（`nous/application/chat/tools/builtin.py` + `tests/unit/application/chat/tools/test_builtin.py` 6/6 pass） |
| P0-2/P0-3/P1-2/P1-3/P2-2: chat.js 整理 | fixer B | 完了（`sandboxRunBlock` → `execCodeBlock`、`/code` → `/exec`、dead 関数削除、console.log 削除） |
| P1-1/P2-1/P2-3: パネル完全削除 + 整理 | fixer C | 完了（`coding_agent.js`/`coding_agent.py` 638行削除、`animateCount` 削除、`settings.js` 整理） |

差分: **11 files / +200 / -769**。CI: Lint ✅, Integration Tests ✅, Unit Tests 1 fail (portrait)

### 5. portrait service CI バグ修正（`a0b96c6`）
- 症状: `test_auto_generate_returns_true_when_all_conditions_met` が CI でのみ fail
- 原因: `_last_generate_time: float = 0.0` の sentinel 値バグ
  - `time.monotonic() - 0.0` の値が runner 起動時間に依存
  - ローカル（uptime 34.7h）: elapsed > 600 → pass
  - CI（uptime 数分）: elapsed < 600 → fail
- 修正: sentinel を `None` に変更。初回 generate 前は interval チェック skip
- `tests/unit/test_portrait_service.py`: 23/23 pass

## 成果
```
4 commits on main (1e7d380 + 4)
a0b96c6 fix(portrait): use None sentinel for _last_generate_time
b1219f8 chore: update SDD docs and ignore uv.lock
0aa3b90 fix(webui): remove sandbox references after MCP migration
d83eebf perf(test): fix pytest OOM by lazy-loading sudachipy and fitz
3af8c1c fix(format): apply ruff format to 14 files
0c5bd8f fix(test): update health endpoint version assertion to 3.0.0
1e7d380 merge: browser & sandbox MCP migration into main
```
ruff: 0 errors / format: clean / pytest: 1605 passed / 7 skipped

## CI 状況
- 29132864247 (CI): queued → 完了待ち
- 29132864273 (Docker Build & Push): in_progress

## 残課題（次セッション）

### 🔴 CRITICAL（ハンドオフから引き継ぎ）
| ID | 内容 | 場所 |
|----|------|------|
| C1 | `memory_create` 重複チェック常時失敗 — `memories` テーブルに `persona` カラム不在 | `_tools_memory.py:65-81` |
| C3 | CORS ミドルウェア完全不在 — WebUIが別ホストからアクセス時エラー | `main.py` |

### 🟠 HIGH（ハンドオフから引き継ぎ）
| ID | 内容 | 場所 |
|----|------|------|
| H1 | `memory_update` の changes 検出ロジック破損 | `_tools_memory.py:290` |
| H4 | `plugin_api_key` 空文字デフォルト = 認証なし | `settings.py:169` |
| H5 | `ChatConfigRepository.get()` カラム位置ハードコード | `chat_config.py:258-338` |

### 🆕 今回セッションで顕在化した課題
- フロントエンドの `__` MCP ゲート開放によるセキュリティ: 任意の MCP ツール（`playwright__browser_navigate` 等）が `/api/chat/{persona}/tool` 経由で呼べる。許可リスト実装が次スプリント
- `mcp` モジュールがローカル uv venv に未インストール（pyproject.toml の `dependencies` に未記載、requirements.txt 経由のため CI/Docker では問題なし）

## .spec/ 最新状態
- `PLAN.md`: WebUI デバッグ版（OpenSandbox MCP 直接ルーティング方針）
- `SPEC.md`: 実装と一致
- `TODO.md`: 全 Phase 完了マーク、次アクション記載

## セッション間運用メモ
- 作業ディレクトリ: `/home/rausraus/code/Nous`（main checkout）
- テスト環境: `uv sync` で `.venv` 作成、`uv run pytest` で実行
- フルテストスイート走らせると 8 分程度（OOM 解消後）
- ローカルで portrait テストが pass し CI で fail する場合、`time.monotonic()` の uptime 依存を疑う

## 次のステップ
1. CI 通過確認（pending）
2. CRITICAL バグ C1 対応（`memory_create` 重複チェック修正）
3. CRITICAL バグ C3 対応（CORS ミドルウェア追加）
4. SECURITY: `__` MCP ゲートに許可リスト実装
5. ハンドオフ更新 → MEMORY.md 更新
