# TODO — sentence-transformers → ONNX Runtime 直叩き

## Phase 0: 事前検証（実装前に必須）

- [ ] T001: ONNX モデル入出力検証 — `onnx-community/ruri-v3-30m-ONNX` の `model.onnx` をロードし input/output names, shapes を確認
- [ ] T002: Ruri v3 ONNX vs sentence-transformers 出力比較 — 同テキストの embedding コサイン類似度 >= 0.999 確認
- [ ] T003: Reranker ONNX モデル検証 — `hotchpotch/japanese-reranker-xsmall-v2` の `model.onnx` をロードし入出力確認
- [ ] T004: Reranker ONNX vs CrossEncoder 出力比較 — 同ペアのスコアが一致するか確認
- [ ] T005: `torch` の全用途 grep — `nous/` `tests/` `mcp-hub/` 全体で `import torch` / `from torch` の全箇所を特定

## Phase 1: EmbeddingModel ONNX 化

- [ ] T006: `model.py` `_load_model()` 再実装 — `onnxruntime.InferenceSession` + `tokenizers.Tokenizer`（post_processor + truncation 設定）
- [ ] T007: `model.py` `encode()` 再実装 — tokenize → session.run → mean_pooling → L2 normalize
- [ ] T008: `model.py` `encode_batch()` 再実装 — バッチ tokenize → session.run
- [ ] T009: `dimension` プロパティ — ONNX 出力 shape から自動検出
- [ ] T010: `reload_model()` / `get_status()` / `unload()` 対応
- [ ] T011: device → providers マッピング + SessionOptions（スレッド数制限）

## Phase 2: RerankerModel ONNX 化

- [ ] T012: `reranker.py` `_load_model()` 再実装 — ONNX InferenceSession + tokenizer（pair 用 post_processor）
- [ ] T013: `reranker.py` `rerank()` 再実装 — pair tokenize → batch run → sigmoid → スコアブレンド
- [ ] T014: `reload_model()` / `get_status()` / `unload()` 対応

## Phase 3: 設定・環境変数・依存関係

- [ ] T015: `settings.py` `ensure_directories()` — `sentence_transformers` / `torch` dir 削除
- [ ] T016: `main.py` — `SENTENCE_TRANSFORMERS_HOME` / `TORCH_HOME` env 削除
- [ ] T017: `requirements.txt` — `sentence-transformers` → `onnxruntime` + `tokenizers` + `huggingface_hub`、torch コメント削除
- [ ] T018: `requirements-prod.txt` — 同上

## Phase 4: テスト更新

- [ ] T019: `tests/unit/test_use_case_adapters.py` — `test_embedding_model_lazy_init` 更新
- [ ] T020: `tests/unit/test_runtime_config.py` — reload callback テスト更新
- [ ] T021: `tests/unit/test_settings.py` — `ensure_directories` 期待リスト更新
- [ ] T022: 新規: embedding 統合テスト（実 ONNX モデル、`pytest.mark.slow` でマーク）
- [ ] T023: 新規: ONNX vs ST 出力回帰テスト（コサイン類似度）

## Phase 5: 検証・ドキュメント

- [ ] T024: 全テストスイート実行（ruff + pytest、1646件パス確認）
- [ ] T025: `docs/llm_usage_guide.md` 更新 — embedding バックエンド変更を反映
- [ ] T026: `.agent/memory/MEMORY.md` 更新
- [ ] T027: コミット・プッシュ

## Phase 6: 事後確認

- [ ] T028: Docker イメージビルド検証（torch が本当に消えたか、requirements 確認）
- [ ] T029: イメージサイズ比較（Before / After）

---

# TODO — mcp-hub/Dockerfile マルチステージ化（別タスク）

## 優先度：中

- [ ] T101: mcp-hub/Dockerfile マルチステージ化設計（builder stage + runtime stage）
- [ ] T102: マルチステージ Dockerfile 実装
- [ ] T103: イメージサイズ検証（ビルド前後比較）
- [ ] T104: docker-compose.yml mcp-hub 動作確認
