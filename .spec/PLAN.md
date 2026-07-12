# PLAN - やりたいこと

## タスク1: sentence-transformers → ONNX Runtime 直叩き (Path C)

- `optimum-onnx` は間接的に torch を引き込むので不採用
- ONNX Runtime 直叩き + `tokenizers`（Rust 製、torch 非依存）で完全 PyTorch フリー
- オラクルの警告を全反映: 事前検証 → 実装 → 回帰テスト の順
- EmbeddingModel と RerankerModel の両方を置き換え
- 公開 API は変えない

## タスク2: mcp-hub/Dockerfile マルチステージ化（別タスク）

- mcp-hub は embedding と無関係。独立して進められる
- マルチステージ化でビルド依存分離、イメージ縮小
