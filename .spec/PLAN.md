# PLAN — ONNX 化後リファクタリング計画

## 背景

sentence-transformers → ONNX Runtime 直叩きへの移行が完了。model.py (285行) と reranker.py (218行) が独立した ONNX 推論を実装している。
@explorer と @oracle のレビューで、以下の改善点が特定された。

## 方針

> oracle の判断: **BaseONNXModel は作らない。** 2ファイルの規模 (計503行) で継承階層を導入するのは YAGNI 違反。
> 代わりに: デッドコード削除 + スレッド安全性修正 + CI グリーン化 を最優先で進める。

## 優先度: 高

### R1: reranker.py スレッド安全性修正（バグ修正）
- `reranker.py` の lazy-load に二重チェックロッキングがない（model.py にはある）
- `_ensure_loaded()` パターンを追加、`rerank()` の冒頭で呼ぶ
- docstring が「Thread-safe」を謳っているのに実装が守れていないバグ

### R2: デッドコード削除
- `_get_session_options()` (model.py:258-262) — 定義のみ、インライン化済みで未使用
- `get_status()` (model.py:193-199, reranker.py:175-182) — コードベース全体で呼び出し元ゼロ
- `encode_batch()` の `batch_size` パラメータ — 受けるだけで未使用

### R3: CI グリーン化（use_cases.py コミット）
- `use_cases.py` のバックグラウンドスレッド化変更をコミット
- 対応するテスト修正を含めて1コミットに
- `test_reranker_not_preloaded_when_disabled` の pre-existing failure を解消

## 優先度: 中

### R4: Dockerfile から build-essential 削除
- onnxruntime, tokenizers, sudachipy すべて pre-built manylinux wheel あり
- AMD64 環境ではビルドツール不要
- ARM64 では sudachipy のみ gcc/g++ 必要の可能性あり → コメントに注記

### R5: _init_vector_store スレッドネスト簡素化
- バックグラウンドスレッド内でさらに `ThreadPoolExecutor(max_workers=1)` + `asyncio.run()` 
- daemon thread 内では asyncio.run() を直接呼べるので簡素化可能

## 優先度: 低

### R6: テストの fixture 化
- `TestAppContextRerankerInstantiation` のセットアップを DRY に
- `_init_vector_store` / `threading.Thread` のパッチを fixture 化

### R7: BaseONNXModel 再検討（条件付き）
- 3つ目の ONNX モデルが登場したタイミングで再検討
- 現状 2つのみ → YAGNI で保留
