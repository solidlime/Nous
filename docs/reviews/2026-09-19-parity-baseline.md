# P0 パリティ・ベースライン記録 — 2026-09-19

v4.0 計画（`docs/superpowers/plans/2026-09-19-v4-release.md`）P0 の完了証跡。

## 1. 赤テスト（xfail strict）— 監査指摘の実在記録

実行: `uv run --with pytest --with pydantic-settings --with mcp --with fastembed pytest tests/parity -q`
結果: **1 passed, 7 xfailed**（pass 1 件は回帰ガード、7 件が赤の記録）

| 監査ID | テスト | 現行違反内容 |
|--------|--------|-------------|
| C1 | `tests/parity/test_parity_envelope.py::test_mcp_*` | 平文 `Error: ...` 返却（共通 envelope なし） |
| C2 | `tests/parity/test_parity_schema_contracts.py::test_item_add_passes_quantity_and_tags_by_keyword` | 位置引数ズレ（quantity→visual_desc, tags→quantity） |
| H3 | `tests/parity/test_parity_http_sideeffects.py::test_http_create_memory_side_effects` | HTTP create が cache 無効化・イベント発火なし |
| H3 | `test_parity_http_sideeffects.py::test_http_update_memory_side_effects` | HTTP update 同上 |
| H3 | `test_parity_http_sideeffects.py::test_http_create_memory_response_schema` | **pass（回帰ガード）** レスポンス形状の固定 |
| M6 | `test_parity_schema_contracts.py::test_memory_delete_by_query_requires_similarity_threshold` | query 削除が top-1 を閾値なしで削除 |
| M7 | `test_parity_schema_contracts.py::test_memory_create_empty_content_returns_validation_envelope` | 空コンテンツが平文エラー（envelope なし） |

各 xfail は `strict=True`。実装が契約を満たすと XPASS で失敗するため、マーカー除去が自動的に強制される。

## 2. get_context トークン実測（監査 C3）

`tests/parity/measure_get_context.py` 実行結果（est tokens = chars/2.5）:

| ケース | 総文字数 | 推定トークン | 主要内訳 |
|--------|---------|------------|---------|
| A: 空ペルソナ | 173 | 69 | 固定部のみ |
| B: 目標10 + insights 3×600字 + summaries 5 | 2,873 | **1,149** | Insights 43.6% / COMMITMENTS 24.0% / Summaries 22.8% |
| C: project 記憶 5×400字 | 3,078 | **1,231** | PROJECT MEMORIES 68.6% |

docstring の主張「~500-800 tokens」に対し、定常ケースで **最大 ~1,231 tokens（主張の 1.5〜2.6 倍）**。
P3（get_context 予算強制）の目標上限はこの実測を基準に設定する。

## 3. P0 完了条件チェック

- [x] parity テスト 3 ファイル（envelope / http_sideeffects / schema_contracts）作成・赤記録済み
- [x] `measure_get_context.py` 作成・実測記録済み（本ファイル §2）
- [x] 計画書・監査レポートをコミット（本コミットに同梱）
