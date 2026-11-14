# 2026-08-15 本番レイテンシ対策（D2 + クエリキャッシュ + enrichment 裏回し）

## 背景

- 症状: memory_create 6-11s / memory_search 非空クエリ 6-16s（空クエリ+タグのみは 13ms）
- 実測（scripts/bench_latency.py、Ryzen 7950X）: warm 推論は全て高速（embed 16ms / rerank 20ペア 119ms / Sudachi 0.5ms）。コールドモデルロード合計 ≈6.1s（embed 3.7s + rerank 2.3s）
- 診断（#081 + 実測の統合）:
  1. リランカーの `_ensure_loaded()`（snapshot_download + ONNX セッション生成）がイベントループ直上の `rerank()`（engine.py:306）内で実行 → **全リクエスト凍結**（2.3s〜、ダウンロード込みで秒級）
  2. enrichment（API キー設定時）が `_run_async().result()` でループブロック（6-10s、create 10950ms と整合）
  3. コールド時 embedding ロード 3.7s（to_thread 済みなのでループは塞がないが、そのリクエストは待つ）
- 決定: リランカーは維持（無効化しない）。D2 + クエリキャッシュ + enrichment background 化のみ実施

## 変更内容

### 1. `OnnxBaseModel.is_loaded` プロパティ追加（infrastructure/embedding/_base.py）
- `self._session is not None` を返すプロパティ。EmbeddingModel / RerankerModel 両方が継承

### 2. リランカー未ロード時スキップ（domain/search/engine.py:301）
- rerank 実行条件に `and self._reranker.is_loaded` を追加
- 未ロード時は 1 回だけ `logger.warning`（毎回出さない。インスタンスフラグ or モジュールフラグで制御）
- 効果: ループ凍結源（2.3s〜）をリクエストパスから除去。ロードはプリロードスレッドに委ねる

### 3. embedding 未ロード時フォールバック（infrastructure/qdrant/adapter.py の search パス）
- semantic search 開始時に embedding 未ロードなら、**バックグラウンドでロードを試行しつつ空結果を返す**（ハイブリッドは keyword/FTS のみで成立）
- 実装: `if not self._embedding.is_loaded: daemon スレッドで `_ensure_loaded()` 起動（自己修復）→ 空リスト return`
- 効果: コールド時の create（dup check 経由）と search を秒級 → 数十 ms に

### 4. ホットリロードのスレッド化（config/runtime_config.py:256-300）
- `on_embedding_change` / `on_reranker_change` の reload ループ（`reload_model()` 呼び出し）を `threading.Thread` で実行し、完了時に `reload_status` を更新
- 理由: admin PUT /api/settings（admin.py:40、async ルート）→ `config.update()` → `_fire_callbacks` が同期待ちし、リロード中ループが 10〜60 秒級ブロックするため
- qdrant コールバックは対象外（asyncio.run 使用、既存挙動維持）

### 5. プリロード失敗ログの可視化（application/use_cases.py:274-322）
- `logger.debug` → `logger.warning`（exc_info=True）に変更（握りつぶし解消、4 箇所）

### 6. クエリキャッシュ（domain/search/engine.py）
- モジュールレベル: `_query_cache: dict[tuple, tuple[float, list[SearchResult]]]` + `threading.Lock`
- 定数: `_CACHE_TTL_S = 30.0`、`_CACHE_MAX = 256`
- `search()` の mode ディスパッチ結果をキャッシュ。**キー = (persona, text, mode, top_k, tags, date_range, min_importance, kind, importance_weight, recency_weight, vector_weight, keyword_weight, similarity_threshold, sort, lifecycle_status, valid_at)**
  - persona は `self._semantic.persona`（semantic 無しなら "default"）。**persona 混在事故の防止に必須**
- 対象: 非空テキストの hybrid / semantic / smart のみ（空テキスト+タグは既に高速なので除外）
- ヒット時は `[r for r in cached]` の浅いコピーを返す（呼び出し側ミューテーション防止。cached リスト自体は filters で新リスト化されるため不変）
- 無効化は TTL のみ（30 秒）。書き込みイベント連携はしない（ponytail: 必要になったら足す）
- emotion / kind / tags / valid_at フィルタと sort はキャッシュの外（毎リクエスト適用）

### 7. enrichment の background 化（3 ファイル）
- `infrastructure/llm/memory_enricher.py`: `async def enrich_async(...)` を追加（既存 `_run_async` 内ロジックを await 化）。既存 `enrich` は同期互換のまま（テスト互換）
- `domain/memory/enrich_service.py`: `enrich_memory` を `async def` に変更し `await self._enricher.enrich_async(...)`（enricher None 時は従来通り何もしない）
- `domain/memory/service.py:187`: `asyncio.create_task(self._enrich_service.enrich_memory(...))` に変更し、モジュールレベル `_background_tasks: set[asyncio.Task]` に登録（GC 防止）
- service.py:201 の evolution タスクも同じ pending セットに登録（既存の GC バグ修正）
- 効果: API キー投入時の create が LLM 待ち 6-10s から解放。importance 更新はレスポンス後に反映（許容）

## テスト影響・追加

- 既存修正（実行して確認）: `enrich_memory` を await する箇所、enrich を直接呼ぶテスト、create_memory 周りのテスト
- 追加テスト:
  1. リランカー未ロード時 rerank がスキップされる（engine 単体）
  2. クエリキャッシュ: 同一クエリ 2 回目がキャッシュヒット（結果同一）/ 浅いコピー / TTL 経過で無効化
  3. enrichment: create が enrichment 完了を待たない（async 化の検証）

## 検証手順

1. `pytest`（特に tests/unit/test_reranker_integration.py / test_engine* / test_runtime_config.py / test_memory_create 関連）
2. 型チェック（mypy or pyright、リポジトリの設定に従う）
3. lint + format
4. `scripts/bench_latency.py` 回帰確認 + E2E で create レイテンシ改善確認

## 対象外（明示）

- B（リランカー無効化）: ユーザーがリランカー維持を選択
- E（ベクトル upsert 分離）: 寄与 30-60ms のみ、後回し
- LIKE 検索 LIMIT / ORT スレッド数調整: 別途

## 品質ゲート

実装（#011）→ テスト → #081 レビュー（PASS 必須）→ GATE（型/テスト/lint/format）→ COMMIT → PUSH
