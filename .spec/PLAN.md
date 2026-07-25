# PLAN — コードベース全体リファクタリング (2026-07-25)

## 現在のフェーズ: 4（発展）

## 出典
`refactor-instructions.md` (ルート直下)

## 完了
- ✅ フェーズ1: 安全基盤 — asyncio TaskGroup, CI改善, Makefile, クイックウィン (commit b151164)
- ✅ フェーズ2: 設計改善 — Result and_then/or_else, SQLiteRepository 強化, MemoryService 5-service Facade 分割
- ✅ フェーズ3: コード清掃 — 5ファイル→13ファイル分解, _get_session_memories 配管実装

## 進行中
### フェーズ4: 発展 (1~3日)
- MCPツールの契約テスト導入
- `ChatConfig` 分割 (602行, 50+フィールド)
- カバレッジ下限のCI強制
- bandit セキュリティlint
