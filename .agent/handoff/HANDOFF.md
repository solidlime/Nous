# HANDOFF — 2026-07-12 12:00

## セッション概要

本セッションでは PyTorch 依存完全排除を目的に、`sentence-transformers` → `onnxruntime` + `tokenizers` への置き換えを完了した。

## 完了したコミット

```
05b2acb docs(memory): embedding ONNX化の学びをMEMORY.mdに記録
c39f9e0 chore: sentence-transformers/PyTorch依存を完全排除、ONNX Runtime直叩きに移行
f0dbbcc refactor(embedding): ONNX Runtime + tokenizers rewrite
```

## 実装サマリ

### 置き換え対象
- `nous/infrastructure/embedding/model.py` — `SentenceTransformer` → `onnxruntime.InferenceSession` + `tokenizers.Tokenizer`
- `nous/infrastructure/embedding/reranker.py` — `CrossEncoder` → 同上
- 公開 API（`encode`, `encode_batch`, `rerank`等）は完全互換、1行も変更なし

### モデル
- Embedding: `onnx-community/ruri-v3-30m-ONNX`（公式 ONNX、mean pooling + L2 normalize 自前実装）
- Reranker: `hotchpotch/japanese-reranker-xsmall-v2`（`onnx/model.onnx` 内蔵）
- Tokenizer: `cl-nagoya/ruri-v3-30m` / モデルと同リポジトリの `tokenizer.json`

### 依存変更
- **削除**: `sentence-transformers>=3.0.0`（間接的に torch, transformers 等も削除）
- **追加**: `onnxruntime>=1.18.0`, `tokenizers>=0.21.0`, `huggingface_hub>=0.20`
- **維持**: `sentencepiece>=0.1.99`

### 設定変更
- `nous/config/settings.py`: `ensure_directories()` から `sentence_transformers`/`torch` キャッシュ削除
- `nous/main.py`: `SENTENCE_TRANSFORMERS_HOME`/`TORCH_HOME` env 設定削除。`HF_HOME` 維持

## 検証状況

```
pytest (全): 1621 passed / 7 skipped (ローカル)
ruff check: 0 errors
ruff format: clean
```

### CI
- Docker Build & Push: ✅ success
- CI (python tests): ⚠️ 1 failed — `TestAppContextRerankerInstantiation::test_reranker_not_preloaded_when_disabled`
  - **これは pre-existing な問題**。`use_cases.py` のバックグラウンドスレッド化変更（未コミット）とテストの不整合

## 未コミットの変更（working tree）

以下のファイルは embedding 変更と**無関係**、別タスクで対応:

| ファイル | 内容 | 備考 |
|---------|------|------|
| `nous/application/use_cases.py` | `_init_vector_store()` をバックグラウンドスレッド化 | 未コミット、テストと不整合あり |
| `tests/unit/test_use_case_adapters.py` | 同上のテスト修正 | 同上 |
| `.dockerignore` | MCP Hub 関連の Docker ignore | 別タスク |
| `Dockerfile` | MCP Hub マルチステージ化 | 別タスク (T101-T104) |
| `docker-compose.yml` | 同上 | 別タスク |
| `nous/api/http/routers/persona.py` | sandbox orchestration 関連？ | 要確認 |
| `requirements-dev.txt` | 新規ファイル (untracked) | 要確認 |

## 🎯 残タスク

### T028-T029: Docker ビルド検証・サイズ比較
- 新しい requirements-prod.txt で Docker ビルド
- PyTorch 非依存のイメージサイズ計測（Before/After で ~800MB 削減見込み）

### T101-T104: mcp-hub/Dockerfile マルチステージ化
- 現在シングルステージ → マルチステージ化でビルド依存分離
- mcp-hub は embedding と無関係、独立して進められる

### Pre-existing issue 修正
- `use_cases.py` のバックグラウンドスレッド化変更を確認し、テストと合わせてコミット

## 注意点

- `requirements-prod.txt` は git 管理下にない（歴史的に untracked）。本番 Docker ビルドで使用
- ONNX モデルは初回起動時に `huggingface_hub.snapshot_download()` で自動ダウンロード（`HF_HOME` キャッシュ）
- `tokenizers` の `post_processor` は自動で `<s>` + text + `</s>` を付与 → 手動 TemplateProcessing 不要
- ONNX Runtime `SessionOptions.intra_op_num_threads = min(4, cpu_count)` でスレッド制限
