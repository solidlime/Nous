# PLAN — コードベース全体リファクタリング (2026-07-25)

## 出典
`refactor-instructions.md` (ルート直下) — 全189 Pythonファイルの静的解析に基づく総合リファクタ計画

## 目的
コードベースの安全性・保守性・開発者体験を向上させる段階的リファクタリング。

## 4フェーズ構成

### フェーズ1: 安全基盤 (1~2日)
- asyncio.create_task() タスクリーク修正
- CIに mypy + 統合テスト追加
- Makefile導入
- .gitignore に node_modules 追加

### フェーズ2: 設計改善 (3~5日)
- MemoryService 責務分割
- Result[T,E] に and_then/or_else 追加
- SQLiteRepository 基底クラス強化

### フェーズ3: コード清掃 (2~4日)
- 大規模ファイル分解 (session_store, memory_repo, prepare)
- 空ディレクトリ削除 + 不足UT追加
- _get_session_memories スタブ実装

### フェーズ4: 発展 (1~3日)
- MCPツール契約テスト
- ChatConfig分割
- カバレッジ下限CI強制

## 現在のステータス
Phase 10 WebUI（キーボードアクセシビリティ）完了。Phase 11 WebUI（モバイル）は TODO として残存。
本リファクタリングは WebUI 計画とは独立して実施する。
