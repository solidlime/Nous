# SPEC — コードリファクタリング (2026-07-20)

## 背景
30件超の重複コード・デッドコード・設計上の問題が検出された。コードベースの健全性を高める。

## P0: 設計上の重複解消

### P0-1: Repository基底クラス抽出
- 5リポジトリ (memory_repo, entity_repo, equipment_repo, block_repo, strength_repo) が同一の `__init__` + `_db` プロパティパターンを持つ
- `nous/infrastructure/sqlite/` に `base_repo.py` を作成し、共通の `__init__(self, connection: SQLiteConnection, persona: str)` を提供
- 差分: `_db` が `memory_db` か `inventory_db` か → ファクトリメソッドかクラス変数で吸収

### P0-2: Result型エラーハンドリング共通化
- ドメインサービス3ファイル (memory/service.py, persona/service.py, equipment/service.py) で `if not result.is_ok: return Failure(result.error)` が25+回出現
- ヘルパー関数 `unwrap_or_propagate(result, logger)` または Result 型自体へのメソッド追加を検討
- 戻り値の型がSuccessの型を変えずにエラーだけ伝播するイディオム

### P0-3: body_decay ↔ emotion_decay 統合
- `body_decay.py` と `emotion_decay.py` が半分以上コピペ
- `compute_*_decay` / `apply_*_decay_if_needed` / ログ出力パターンが完全一致
- `DecayProcessor` 基底クラスまたは共通関数に抽出

### P0-4: デッドコード除去
- `session_store.py:802` — `SessionWindow` の再定義 (F811)
- `inference.py:6` — `logging` import 未使用
- `skill.py:4` — `os` import 未使用

## P1: ボイラープレート削減

### P1-1: MCPツール エラー応答統一
- 4ファイル間で `{"error": str(e)}` と `"result_summary": str(e)` が混在
- 共通のエラー応答ビルダー `mcp_error_result(error, success=False)` を作成し `result_summary` + `success` 形式に統一

### P1-2: HTTPルーター エラーハンドリング抽出
- 6ファイルで `JSONResponse({"error": str(result.error)}, status_code=500)` が一字不変
- `http_error_response(result)` ユーティリティに関数抽出

### P1-3: テストフィクスチャ conftest.py集約
- `SQLiteConnection(str(tmp_path), "test")` が14ファイルで重複
- `tests/unit/conftest.py` に `sqlite_conn` フィクスチャとして定義、全テストファイルから削除

## P2: 改善・整備

### P2-1: memory_repo.py 過剰try/except削減
- 27メソッド中、参照系 (~15メソッド) はtry/except不要（rollback不要）
- 更新系のみtry/exceptを残し、参照系はクリーンに

### P2-2: pyproject.toml バージョン修正
- `version = "3.0.0"` → `"3.5.0"` に実コードと一致させる

### P2-3: value_objects二重定義整理
- `memory/value_objects.py` の `ALLOWED_EMOTIONS = list(_VALID_EMOTIONS)` を削除し、直接 `_VALID_EMOTIONS` を参照

### P2-4: _row_to_* 変換パターン共通化（後回し候補）
- 6リポジトリに散らばる dict→dataclass 変換。型が異なるため共通化の抽象度が高く、テストリスク大 → 今回スコープ外とし、TODOにメモのみ残す
