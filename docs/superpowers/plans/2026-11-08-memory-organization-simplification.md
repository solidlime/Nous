# 記憶整理機能の縮小 — 4 worker を削って wiki/consolidation に一本化する

- 日付: 2026-11-08
- 判断者: ユーザー（3 点の選択で確定）
- 状態: 計画（実装前）

## 1. 背景

2026-11-08 時点の「記憶の整理機能」は 6 worker + 書き込み時 dedup だった。

| 機能 | 実体 | 行数 | 本番実績 |
|---|---|---|---|
| Decay（FSRS 忘却曲線） | `nous/application/workers/decay_worker.py` | 426 | `strength<0.2` かつ 30 日無活動で archived（0.005 は保存スキップの閾値）。監査イベント無し＝観測不能 |
| Consolidation（gist） | `consolidation_worker.py` | 543 | consolidated 1,366 件（全体 28.4%）、最終 2026-11-05 |
| Freshness（LLM 有効性判定） | `freshness_worker.py` | 382 | verdict 22 件のみ、最終 2026-11-07 |
| Enrichment（importance/関係） | `enrichment_worker.py` + `enrich_service.py` | 370 + 128 | memory_links summarizes 2,338 / semantic 2,498 |
| Curation（日次 journal/profile） | `curation_worker.py` | 619 | **無効**（既定 false）、journal 0 件 |
| Wiki 編纂（ドリーミング） | `wiki_worker.py` | 673 | 3 ページ + index、2026-11-08 から毎日 03:00 |
| 書き込み時 dedup | `MemoryWriteService` | — | 完全一致・active 限定 |

ユーザー判断（2026-11-08）:

1. **Freshness は削除**。session_begin の「期限が近い約束」先出し（`pending_freshness`）も廃止。
2. **Curation は削除**（既定無効・journal 0 件）。
3. **Enrichment は削除**。相乗りしている自発的内省（`brain.introspection_spontaneous`）も一緒に削除、novelty boost も削除。
4. **Decay ごと廃止**。強度・忘却曲線の概念を捨て、`active → (編纂されたら archive) → archived` の一本道にする。整理は wiki/consolidation に一本化。

結果として本番の常駐 worker は **consolidation + wiki の 2 本**になる。

## 2. 削除マップ

### 2.1 A: Freshness（kanban #28）

- モジュール: `nous/application/workers/freshness_worker.py`（382 行）
- 設定: `nous/config/settings.py:389 class FreshnessConfig`
- 起動: `nous/main.py:295-297`
- MCP 面: `nous/api/mcp/_tools_persona.py:140` `pending_result` → `:186 pending_freshness=` と
  `nous/api/mcp/_tools_helpers.py:393, 502-506` の「⏰ 期限切れ間近」ブロック
- テスト: `tests/unit/test_freshness_worker.py`、`tests/unit/test_pending_freshness_begin.py`

### 2.2 B: Curation（kanban #28）

- モジュール: `nous/application/workers/curation_worker.py`（619 行）
- 設定: `nous/config/settings.py:198 class CurationConfig`
- 起動: `nous/main.py:289-293`（`settings.curation.enabled` 分岐ごと削除）
- 環境変数: `NOUS_CURATION__*`（本番未設定）
- 書き込み先 `memory_blocks` は**残す**（`block_repo.py` は独立した core memory 基盤）
- テスト: `tests/unit/test_curation_worker.py`

### 2.3 C: Enrichment + introspection + novelty（kanban #29）

- モジュール: `enrichment_worker.py`（370 行）、`nous/domain/memory/enrich_service.py`（128 行）
- 設定: `nous/config/settings.py:126 class MemoryEnrichmentConfig`
- 起動: `nous/application/use_cases.py:472-474`（`_enrichment_workers` dict 含む）
- queue: enrichment queue のテーブル・リポジトリ・`wiring_events.py` のエンキュー
- 相乗り削除: `nous/application/chat/introspection.py` の drain 後フック経路（自発的内省）
- テスト: `test_enrichment_worker.py`, `test_enrichment_queue_repo.py`,
  `test_memory_enricher_usage.py`, `test_memory_enrichment_config.py`, `test_introspection.py`,
  `test_introspection_prompt_override.py`, `test_spontaneous_clock.py`
- **残す**: `importance` 列（書き込み時 0.5 固定）、`min_importance` 引数、MCP/ダッシュボードの表示
- **残す（重要・Explore 実測 2026-11-08）**: `MemoryEnrichmentConfig` クラス。
  `nous/application/hooks/memory_extraction.py:82-89`（本番 pi hook の抽出 LLM 鍵解決）と
  `nous/application/workers/consolidation_worker.py:83-95`（gist LLM のフォールバック）が借りている。
  消すと本番の記憶抽出が静かに止まる。クラス名を `LLMConfig` に改めるのは可（`Settings.memory_enrichment`
  のフィールド名は env 互換のため据え置き）。
- **残す**: `MemoryEnricher.classify_contradiction`（`nous/domain/memory/evolution_service.py:121` が使う別機能）。
  `enrich_async` / `_parse_response` は削除する。

### 2.4 D: Decay + FSRS + Reflection（kanban #30）

- モジュール: `decay_worker.py`（425 行）
- 設定: `nous/config/settings.py:113 class ForgettingConfig`
- 起動: `nous/application/use_cases.py:437-459`、`nous/application/workers/__init__.py:4,6`
- ドメイン: `nous/domain/memory/entities.py` の stability / difficulty / strength /
  emotion_amplify / `importance_scaled_exponent`
- テーブル: `memory_strength`（**残す**。履歴・DROP は別判断）。読み手は
  `nous/infrastructure/sqlite/strength_repo.py:17,28,70`（唯一の SQL 実装）、
  `nous/domain/memory/query_service.py:156-195` ←`service.py:343-351`← MCP `_tools_memory.py:137,512`、
  `nous/domain/search/engine.py:868-875`、`ranker.py:109-140`、`vector_stack.py:210`,
  `evolution_service.py:240-247`、`persona_dashboard.py:89-98`、`_tools_memory.py:573-592`。
  `entity_repo.py:316-402` と `mot_thoughts.py` が読むのは `memory_links` であって
  `memory_strength` ではない（当初の記載は誤り）。
- 相乗り: 周期 Reflection（`nous/application/chat/reflection.py`, `ReflectionEngine`,
  `session_config.REFLECTION_INTERVAL=24` サイクル）、due cue の実体化（`decay_worker.py:126`）
- テスト: `test_decay_worker.py`, `test_emotion_decay.py`

#### 調査で判明した「切っても壊れない」こと（実測）

- `due_cues()` は**純粋関数**で、`_tools_persona.py:151`（session_begin）と
  `context_loader.py:212`（チャット）が直接呼んでいる。DecayWorker は「期限記憶を実体化する」
  だけで、表示経路は Decay と無関係 → **Decay を消しても期限表示は残る**。
- `memory_blocks`（Curation の profile 書き込み先）は `block_repo.py` の独立基盤。
- **ただし due_reminder 記憶を実体化するのは `decay_worker.py:87-124` だけ**。Decay を消すと
  「⏰ 期限が近い約束」の one-shot 節（`_tools_persona.py:159-160` / `_tools_helpers.py`）に
  供給元が無くなる。wiki_worker か consolidation_worker へ移すか、機能ごと落とすかを #30 で決める。

## 3. 決定的な依存: consolidation の入力

`nous/application/workers/consolidation_worker.py:283-285`

```python
archived = [
    m for m in all_result.value
    if m.lifecycle_status == "archived" and getattr(m, "valid_until", None) is None
]
```

- **入力は archived の全件**。Decay 廃止後は wiki の `_archive_sources` だけが供給源になる。
- `_save_consolidated` には**既存 gist との重複判定が無い**（sources は archived のまま、
  毎サイクル同じクラスタから新しい gist を作り得る）。1,366 件という件数の一因。
- したがって kanban #31 で「`link_type='summarizes'` 済みの記憶を除外する」条件を足す。

供給量の試算: wiki は 2 topic/cycle × 最大 40 sources = **最大 80 件/晩**が archived に沈む。

## 4. 実装順序

依存の向きから、独立に切れる A/B → C → D → 入力契約の付け替え（#31）の順。

1. **#28** Freshness + Curation 削除（他と交差しない）
2. **#29** Enrichment + introspection + novelty 削除（importance は 0.5 固定で存置）
3. **#30** Decay/FSRS/Reflection 廃止（`memory_strength` の読み手を先に潰す）
4. **#31** consolidation の入力契約を wiki-archived に変更 + 重複除外 + 面の後始末 + デプロイ

各段で `pytest tests/unit` / `ruff` / `mypy` delta 新規 0 を確認してから次へ進む。
mypy は CI と同じ baseline 差分で判定する（絶対値は環境差で嘘をつく）。

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| consolidation の入力が細る | #31 で供給量を実測し、`min_memories_per_group` と `max_consolidated` を実データで見直す |
| gist の重複生成 | `summarizes` リンク済みを除外（#31） |
| importance が 0.5 固定になる | 検索の `min_importance` は既定 0 なので影響なし。goal ツールが 0.9 に上げる経路は残る |
| 忘却が無くなり active が単調増加 | 唯一の archive 経路が wiki 編纂。粒度（2 topic/晩）では追いつかない可能性 → #31 で本番の増加率を測る |
| 既存データ | `memory_strength`・enrichment queue・freshness verdict は**削除しない**（履歴）。テーブル drop は別判断 |

## 6. 検証計画

- 各段: `pytest tests/unit`（現在 3,013 passed が基準）、`ruff check`、mypy delta 新規 0。
- 最終: 本番ログに `ConsolidationWorker` と `WikiWorker` だけが起動していること、
  `DecayWorker` / `EnrichmentWorker` / `FreshnessWorker` / curation の行が消えていること。
- 03:00 の wiki 編纂後に archived が増え、翌日の consolidation がそれを gist 化すること。
