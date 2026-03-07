# KNOWLEDGE - ドメイン知識・調査結果

## 業務・ドメイン知識
- Nous は AIキャラクター（ヘルタ等）を自律稼働させるフレームワーク
- MemoryMCP（ポート 26262）とは独立した別プロジェクト

## 調査・リサーチ結果
-

## 技術的な知見
- FastMCP は stateless_http=True で /mcp にマウント
- Qdrant コレクション prefix: `nous_`（MemoryMCP の `memory_` と区別）
- ローカル MCP モジュールは `nous_mcp/`（pip の `mcp` パッケージと衝突回避）

## 決定事項と理由
-
