# SPEC — Phase 1: 検証・即時改善

> 出典: `.spec/PLAN.md` (2026-07-26) P1-1 / P1-2
> 旧 SPEC (Phase 4: ChatConfig分割・契約テスト・CI強化) は完了済み。MEMORY.md 参照。

---

## SPEC-1.1: 記憶減衰・想起スコアの動作検証 (P1-1)

**背景**: `memory_strength` テーブル、`ForgettingCurveRanker`、`DecayWorker` は実装済み。
しかし 52件の FK constraint failed（orphan memory_strength records）が発生しており、
減衰サイクルが想定通り機能しているか未確認。

### 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | DecayWorker 可観測性 | 減衰サイクル毎の処理件数・更新件数・スキップ件数をデバッグログに出力 |
| R2 | オーファンクリーンアップ | `memory_strength` の orphan レコード（memories 側に存在しない memory_id）を削除する migration 追加 |
| R3 | エラーログ集約 | `strength_repo` の FK エラーを1件毎でなくサマリー集計（N件を1行）で出力 |
| R4 | 統合テスト | 検索結果に減衰スコアが反映されること（古い記憶が新しい記憶より下位になる等）を確認する統合テスト追加 |

### 制約
- migration は既存のバージョン規約（v0XX 連番）に従う
- 後方互換: 既存の `memory_strength` スキーマは変更しない（削除のみ）

---

## SPEC-1.2: 応答検証の動作確認 (P1-2)

**背景**: 応答検証機構（キャラクター整合性チェック）の実装状況が不明。
`PostProcessStep` 内の `_safe_reflection()` / `_safe_mental_model()`、
Author's Note 強制注入との矛盾検出の有無を確認する。

### 要件

| # | 要件 | 内容 |
|---|------|------|
| R1 | 検証パス洗い出し | 全 PostProcessStep の検証経路をコードリードで一覧化（ドキュメント化） |
| R2 | 検出能力テスト | 現在の検証がキャラクター矛盾（口調崩壊・性格不一致）を検出できるかのテストケース作成 |
| R3 | 簡易後処理検証 | 不足がある場合のみ、ルールベース（LLM呼出不要）の後処理検証パスを追加 |

### 制約
- R3 は R2 の結果が「検出不可」の場合のみ実施（YAGNI）
- ルールベース検証はペルソナ非依存であること（口調・感情表現はペルソナ定義側の責務）

---

## 検証要件

| # | 項目 | 方法 |
|---|------|------|
| V1 | P1-1 関連テスト | `pytest tests/unit/test_decay_worker.py tests/unit/test_memory_strength.py` + 新規テスト |
| V2 | P1-2 関連テスト | 新規テスト + `pytest tests/unit/test_chat_pipeline.py` の関連部分 |
| V3 | 回帰確認 | 変更モジュールに直接依存するテストファイルのみ個別実行（**フルスイート禁止: メモリ不足のため**） |
| V4 | lint | `ruff check` PASS |
| V5 | migration | 新規 migration が既存DBに対して冪等に適用できること |

## 実装方針
- 調査（探索）: #009 explorer ×2 並列（P1-1 系 / P1-2 系）
- 実装: #011 fixer（P1-1 と P1-2 は独立のため並列可能）
- テスト実行はスコープ限定（対象ファイル指定）
