# SPEC — 技術仕様・要件定義

## チャットメッセージ編集・削除・自動再生成

### 機能要件
- [x] FR-C1: ユーザーメッセージ編集後、後続メッセージが存在する場合は自動で切捨て+LLM再生成
- [x] FR-C2: 最終メッセージの編集時は再生成しない（後続がないため）
- [x] FR-C3: ユーザーメッセージ削除ボタン（trash-2アイコン）
- [x] FR-C4: 削除時に確認ダイアログ（後続件数を表示）
- [x] FR-C5: 削除後、直前のユーザーメッセージで自動再生成
- [x] FR-C6: 削除ボタンは赤色ホバー効果

### 設計方針
- バックエンド変更なし（既存 `POST /rollback` API を流用）
- ブランチ機構なしのフラット配列モデルを採用
- 編集/削除 → truncate → 再生成の一貫したパイプライン

### 変更ファイル
| ファイル | 内容 |
|---------|------|
| `nous/api/http/static/chat/chat-history.js` | editChatMessage改造、deleteChatMessage追加 |
| `nous/api/http/static/chat/chat-send.js` | 削除ボタン追加 |
| `nous/api/http/static/chat.css` | 削除ボタンホバー色 |

---

# sentence-transformers → ONNX Runtime 置き換え 仕様（Path C: 直叩き）

## 背景

`optimum-onnx` は間接的に torch を引き込むため、PyTorch 完全排除には ONNX Runtime 直叩きが必須。
Ruri v3 には公式 ONNX モデル（`onnx-community/ruri-v3-*-ONNX`）が存在し、
Reranker（`hotchpotch/japanese-reranker-xsmall-v2`）にも ONNX 版あり。

## 目的

- PyTorch 依存を完全排除（Docker イメージ ~800MB 削減）
- `sentence-transformers` を依存から外す
- EmbeddingModel / RerankerModel の公開 API は完全互換維持（呼び出し元変更ゼロ）

## アーキテクチャ

```
Before: SentenceTransformer(model_name).encode(texts)
After:  onnxruntime.InferenceSession(onnx_model).run(...) + tokenizers.Tokenizer(...).encode(text)

Before: CrossEncoder(model_name).predict(pairs)
After:  onnxruntime.InferenceSession(onnx_model).run(...) [CrossEncoder ONNX]
```

### EmbeddingModel 内部設計

```
_load_model():
  1. huggingface_hub.snapshot_download("onnx-community/ruri-v3-30m-ONNX") → model.onnx
  2. ort.InferenceSession(model.onnx, providers=[...], sess_options)
  3. tokenizers.Tokenizer.from_pretrained("cl-nagoya/ruri-v3-30m")
  4. tokenizer.post_processor = TemplateProcessing("$A [SEP]", ...)  ← CLS/SEP 自動付与
  5. tokenizer.enable_truncation(max_length=512)
  6. _dimension = 出力テンソルの最終次元から取得

encode(text, is_query=False):
  1. prefixed = f"{PREFIX}{text}"
  2. encoding = tokenizer.encode(prefixed) → input_ids, attention_mask
  3. np.array 化（int64, batch=1 用に expand_dims or stack）
  4. outputs = session.run(None, {"input_ids": ids, "attention_mask": mask})
  5. last_hidden_state = outputs[0]  ← モデル出力形式に依存、事前検証必須
  6. mean_pooling + L2 normalize (attention_mask 考慮)
  7. return np.ndarray(dim,)

encode_batch(texts, is_query=False, batch_size=32):
  1. 同じくバッチ単位で tokenize → InferenceSession.run
```

### RerankerModel 内部設計

```
_load_model():
  1. snapshot_download("hotchpotch/japanese-reranker-xsmall-v2") → model.onnx
  2. ort.InferenceSession(model.onnx, providers=["CPUExecutionProvider"])
  3. tokenizers.Tokenizer.from_pretrained("hotchpotch/japanese-reranker-xsmall-v2")
  4. post_processor = TemplateProcessing("$A [SEP] $B [SEP]", ...)  ← query-doc pair

rerank(query, results, contents, top_k):
  1. pairs = [(query, content) for each result with content]
  2. tokenize each pair as "[CLS] query [SEP] doc [SEP]"
  3. batch InferenceSession.run → logits
  4. sigmoid → scores
  5. スコアブレンド: blended = rerank_score * 0.7 + original_score * 0.3
```

## 変更ファイル一覧

### コア変更
| ファイル | 変更内容 |
|---------|---------|
| `nous/infrastructure/embedding/model.py` | SentenceTransformer → onnxruntime.InferenceSession + tokenizers.Tokenizer |
| `nous/infrastructure/embedding/reranker.py` | CrossEncoder → onnxruntime.InferenceSession + tokenizers.Tokenizer |
| `nous/config/settings.py` | `ensure_directories`: sentence_transformers/torch dir削除、`cache_dir` 維持 |
| `nous/main.py` | SENTENCE_TRANSFORMERS_HOME と TORCH_HOME env 削除、HF_HOME は維持 |
| `requirements.txt` | sentence-transformers→onnxruntime+tokenizers+huggingface_hub、torch コメント削除 |
| `requirements-prod.txt` | 同上 |

### テスト変更
| ファイル | 変更内容 |
|---------|---------|
| `tests/unit/test_use_case_adapters.py` | `test_embedding_model_lazy_init` のモデルロード確認を ONNX 版に更新 |
| `tests/unit/test_runtime_config.py` | reload callback テストのモデルチェックを更新 |
| `tests/unit/test_settings.py` | `ensure_directories` の期待ディレクトリリスト更新 |

### ドキュメント変更
| ファイル | 変更内容 |
|---------|---------|
| `docs/llm_usage_guide.md` | embedding バックエンド変更を反映 |
| `.agent/memory/MEMORY.md` | 学びを記録 |

## 機能要件

### FR-1: 事前検証
- [ ] ONNX モデルの入出力形式検証スクリプト（`model.onnx` の input/output names/shapes 確認）
- [ ] Ruri v3 ONNX モデルの出力を sentence-transformers 出力と比較（コサイン類似度 >= 0.99 確認）
- [ ] Reranker ONNX モデルの同様の検証
- [ ] `nous/` + `tests/` 全体の `import torch` / `from torch` grep（embedding 以外の torch 使用の有無を最終確認）

### FR-2: EmbeddingModel ONNX 化
- [ ] `_load_model()`: `onnxruntime.InferenceSession` + `tokenizers.Tokenizer` による遅延ロード
- [ ] `encode()` / `encode_batch()`: tokenize → InferenceSession.run → mean_pooling → L2 normalize
- [ ] `dimension` プロパティ: ONNX モデル出力の最終次元から自動取得
- [ ] `reload_model()`: 旧モデルフォールバック維持
- [ ] `get_status()` / `unload()`: ONNX 対応
- [ ] device → onnxruntime providers mapping: CPU→CPUExecutionProvider, CUDA→CUDAExecutionProvider
- [ ] onnxruntime SessionOptions: intra_op_num_threads 制限（コンテナ環境考慮）
- [ ] query/document プレフィックス（`検索クエリ: ` / `検索文書: `）維持
- [ ] デフォルトモデル名: `onnx-community/ruri-v3-30m-ONNX`

### FR-3: RerankerModel ONNX 化
- [ ] `_load_model()`: `onnxruntime.InferenceSession` + `tokenizers.Tokenizer`
- [ ] `rerank()`: pair 形式 tokenize → batch run → sigmoid → スコアブレンド
- [ ] `reload_model()` / `get_status()` / `unload()`: 対応
- [ ] デフォルトモデル: `hotchpotch/japanese-reranker-xsmall-v2`（ONNX ファイルを直接指定）
- [ ] スコアブレンド（0.7:0.3）維持

### FR-4: 設定・環境変数変更
- [ ] `settings.py` `ensure_directories()`: `sentence_transformers` / `torch` ディレクトリ削除
- [ ] `main.py`: `SENTENCE_TRANSFORMERS_HOME` / `TORCH_HOME` env 削除、`HF_HOME` は維持
- [ ] onnxruntime はモデルを `HF_HOME` 経由 `snapshot_download` で管理（追加キャッシュ dir 不要）

### FR-5: 依存関係
- [ ] 追加: `onnxruntime>=1.18.0`, `tokenizers>=0.21.0`, `huggingface_hub>=0.20`
- [ ] 削除: `sentence-transformers>=3.0.0`
- [ ] 間接依存解消: torch, transformers, scipy 等が削除される
- [ ] `sentencepiece>=0.1.99`: 維持（tokenizer が依存）

### FR-6: テスト
- [ ] ONNX モデルを使用した統合テスト: `pytest.mark.slow` で分離、CI キャッシュ利用
- [ ] regression テスト: sentence-transformers 出力とのコサイン類似度 >= 0.999
- [ ] 既存テスト更新: Mock を `InferenceSession.run` に差し替え
- [ ] エラーフォールバックテスト: ネットワーク不通時の degraded 状態確認

## 非機能要件

- **パフォーマンス**: 推論速度 2x 以上（sentence-transformers 比）
- **メモリ**: モデルロード時メモリ 500MB 未満（現状 ~1.2GB）
- **互換性**: EmbeddingModel / RerankerModel の公開 API 変更なし
- **テスト**: 全既存テスト（1646件）パス

## リスクと緩和策

| リスク | オラクル指摘 | 緩和策 |
|--------|------------|--------|
| ONNX モデルに pooling 組み込み済みで二重 normalize | Pooling 戦略の罠 | FR-1 事前検証でモデル出力形式を確認、動的に分岐 |
| `tokenizers` 直だと CLS/SEP 抜け | Tokenizer の罠 | `post_processor` で `TemplateProcessing` 設定 |
| `snapshot_download` 失敗で起動不能 | エラーハンドリング | `local_files_only` フォールバック、degraded 状態へ |
| ONNX と PyTorch 出力の微小差異 | 数値的差異 | regression テストで許容範囲（cosine >= 0.999）確認 |
| `asyncio.to_thread` + ONNX でのスレッドプール枯渇 | スレッドセーフ | `inter_op_num_threads` 制限 + Semaphore 検討 |
