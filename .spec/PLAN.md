# PLAN — コードベース全体リファクタリング (2026-07-25)

## 現在のフェーズ: 2（設計改善）

## 出典
`refactor-instructions.md` (ルート直下)

## 完了
- ✅ フェーズ1: 安全基盤 — asyncio TaskGroup, CI改善, Makefile, クイックウィン (commit b151164)

## 進行中
### フェーズ2: 設計改善 (3~5日)
- MemoryService 責務分割（689行→4サービス）
- Result[T,E] に and_then/or_else 追加
- SQLiteRepository 基底クラス強化

## 残り
### フェーズ3: コード清掃 (2~4日)
- 大規模ファイル分解

### フェーズ4: 発展 (1~3日)
- 契約テスト、ChatConfig分割、カバレッジCI強制
