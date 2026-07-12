# TODO — 全タスク統合リスト

## 完了済み

### sentence-transformers → ONNX Runtime
- [x] T001-T005: Phase 0 事前検証（ONNXモデル入出力確認、ST出力比較、torch grep）
- [x] T006-T011: EmbeddingModel ONNX化（model.py 全メソッド）
- [x] T012-T014: RerankerModel ONNX化（reranker.py 全メソッド）
- [x] T015-T018: 設定・環境変数・依存関係更新（settings, main, requirements）
- [x] T019-T023: テスト更新 + スキップ7件解消（zipデータ不在テスト削除）
- [x] T024-T027: 全テスト実行 + ドキュメント + コミット
- [x] T028: Dockerfile から torch 明示的インストール削除

### mcp-hub
- [x] T101: mcp-hub/Dockerfile マルチステージビルド化

---

## 優先度：高（リファクタリング）

- [ ] R1: reranker.py スレッド安全性修正 — `_ensure_loaded()` パターン追加（`rerank()` の lazy-load に二重チェックロッキングがないバグを修正）
- [ ] R2: デッドコード削除
  - `_get_session_options()` (model.py:258-262) — インライン化済みで未使用
  - `get_status()` (model.py:193-199, reranker.py:175-182) — 呼び出し元ゼロ
  - `encode_batch()` の `batch_size` パラメータ — 未使用
- [ ] R3: CI グリーン化 — `use_cases.py` のバックグラウンドスレッド化変更 + テスト修正をコミット

## 優先度：中

- [ ] R4: Dockerfile から `build-essential` 削除（全依存が pre-built wheel、不要）
- [ ] R5: `_init_vector_store` の `ThreadPoolExecutor(asyncio.run())` 二重ネスト簡素化

## 優先度：低

- [ ] R6: `TestAppContextRerankerInstantiation` のテスト fixture 化
- [ ] R7: BaseONNXModel 導入の是非を再検討（3つ目のONNXモデル登場時）

## 別タスク枠

- [ ] T029: Docker イメージビルド検証・サイズ比較（実ビルドして Before/After 計測）
- [ ] T102-104: mcp-hub CI 確認 + docker-compose 動作確認 + requiremets-dev.txt 整理
