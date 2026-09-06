# 脳シミュレーション拡張 Implementation Plan

> **For agentic workers:** 各タスクは独立した #011 レーンとして実行する。所有ファイルは排他——所有外ファイルは絶対に触らない。ステップは checkbox 追跡。

**Goal:** 神経科学由来 6 テーマ（感情修飾/新規性ゲート/RIF/gist 変換/分離・補完/分相化）+ EnrichmentWorker + 脳シミュレーション設定 UI + グラフ発火可視化を実装する。

**Architecture:** 統合スケジューラは作らない（#081 ADR）。既存 DecayWorker/ConsolidationWorker を残置し、EnrichmentWorker（カーソル+周上限）を追加。novelty ゲートは EnrichmentWorker パスの独立ステップ。

**Tech Stack:** Python 3（threading.Thread ワーカー）、SQLite、Qdrant、バニラ JS + vis-network、Jinja sections。

**設計書:** `docs/superpowers/specs/2026-09-06-brain-simulation-design.md`（契約の权威）

## Global Constraints（全レーン共通）

- wiring emit 規約: 全 emit は `try/except Exception + logger.debug("wiring emit failed", exc_info=True)` で包む。emit は「成功後のみ」発火させる（成功フラグ規約、commit 0a59a10b 前例）
- 床: `min_strength = 0.005`（settings.py:91）を全強度変換で尊重。importance は全機構で不変
- 新依存の追加禁止
- 設定キー名（レーン間契約、lane1 が session_config.py に定義・lane3 は JS のみで消費）:
  `brain_enrich_auto_run` / `brain_enrich_interval_seconds`(=60) / `brain_enrich_batch_limit`(=5) / `brain_novelty_sim_threshold`(=0.75) / `brain_novelty_importance_threshold`(=0.6) / `brain_novelty_stability_multiplier`(=2.0) / `brain_emotion_gain_k`(=0.5) / `brain_rif_suppression_rho`(=0.05) / `brain_link_separation_threshold`(=0.75) / `brain_graph_flash_enabled`(=true)
  （`memory_enrichment_auto_run`/`interval` は旧キー——脳シミュレーション UI が新キーを正とし、旧キーの UI 項目は置換で消える）
- テスト実行: `pytest tests/unit/... -q`（ルート）/ `npx vitest run <file>` は **`nous/api/http/static` 配下で実行**（ルートは別 vitest 4.x を拾う）
- コミット: 各レーン末尾で1コミット、メッセージは conventional（`feat(brain): ...` / `feat(ui): ...`）
- 禁止: `git push --force` / `git commit --no-verify`

---

### Task 1（lane1）: EnrichmentWorker + 設定キー + DecayWorker 強化

**Files（所有）:**
- Create: `nous/application/workers/enrichment_worker.py`
- Modify: `nous/application/workers/decay_worker.py`（stability 型 replay_fire emit + gist 除外述語）
- Modify: `nous/application/use_cases.py:558-569`（EnrichmentWorker 起動・停止経路）
- Modify: `nous/domain/session_config.py`（新設定キー定義——**session_config.py の唯一の所有者**）
- Modify: `nous/domain/memory/wiring_events.py`（`WIRING_KINDS` に `novelty_gate` 追加 + docstring。**backend の wiring_events.py は lane1 の所有**——novelty_gate を発火する唯一のレーンのため。フロントの kind 対応は lane3）
- Test: `tests/unit/test_enrichment_worker.py`（新規）、`tests/unit/test_decay_worker.py`（拡張）、`tests/unit/test_wiring_feed.py`（novelty_gate emit の 1 テスト追加）

**Interfaces（Produces — lane2/3 が依存）:**
- `session_config` に Global Constraints の 10 キーを定義（デフォルト値も契約どおり）
- `EnrichmentWorker.__init__(self, context: AppContext, config: ChatConfig | None = None)`、`start()` / `stop()` — DecayWorker（decay_worker.py:27,45）と同一パターン
- `use_cases.py`: forgetting/enrichment 有効時に `EnrichmentWorker(ctx, config)` を生成・start、`stop_decay_workers(timeout)` に追加停止を含める

**Steps:**

- [ ] session_config.py に 10 キーを追加（デフォルト値は Global Constraints どおり）。既存 `memory_enrichment_auto_run`/`memory_enrichment_interval` フィールドは削除しない（後方互換・置換は lane3 が担当）
- [ ] `test_enrichment_worker.py` を先に書く（TDD）:
  - `test_cursor_only_recent`: カーソル以降に作成された記憶のみ enrich 呼び出しを assert（2 周目で 1 周目の対象を再処理しない＝冪等）
  - `test_batch_limit`: 1 周あたり `brain_enrich_batch_limit`(5) 件で打ち切りを assert
  - `test_novelty_gate_step`: 新規記憶（ベクトル類似全件 < 閾値）→ stability が `brain_novelty_stability_multiplier` 倍になり wiring `novelty_gate` emit を assert（空検索結果 → max_cosine=0.0 → novel として発火することも含める）
  - `test_novelty_not_fires_when_similar`: 類似度が閾値以上 → ブーストなし・emit なし
  - `test_emits_follow_convention`: emit 失敗（モックで raise）でもループ継続
- [ ] `enrichment_worker.py` 実装。構造は DecayWorker（decay_worker.py:27-62）踏襲: `__init__(context, config)` → `start()` が `threading.Thread(target=self._run, daemon=True)` → `_run(): while not stop_event: cycle; stop_event.wait(interval)`。interval は `brain_enrich_interval_seconds`。cycle 内: (1) novelty ゲート（LLM 不要・カーソル対象に無条件実行、`brain_novelty_sim_threshold`/`brain_novelty_importance_threshold` で判定、ベクトル検索は `contradiction.py:223` `find_potential_contradictions` と同パターンで VectorStore.search(persona, content, limit=10) を直接使う）→ (2) LLM enrichment（`MemoryEnrichService.enrich_memory` を既存記憶に回す、`brain_enrich_batch_limit` で打ち切り）
- [ ] `decay_worker.py` に (a) decay サイクルで stability 型 `replay_fire` emit（emit 規約どおり、weight=更新後 strength）(b) gist 除外述語: `kind == "semantic" AND source_type == "consolidated"` の記憶は減衰対象から除外 (c) 感情減衰緩和: 減衰率に `1/(1 + 0.5 * emotion_intensity)` を掛ける（係数範囲 1.0–0.5、lane2 の `brain_emotion_gain_k` とは別の内部固定係数）を追加
- [ ] `test_decay_worker.py` 拡張: `test_stability_replay_fire` / `test_gist_resists_decay`（consolidated semantic は strength 不変）/ `test_emotion_eases_decay`
- [ ] `use_cases.py` 起動経路に EnrichmentWorker を追加
- [ ] 実行: `pytest tests/unit/test_enrichment_worker.py tests/unit/test_decay_worker.py tests/unit/test_app_context_registry.py -q` → 全 PASS
- [ ] Commit: `feat(brain): add EnrichmentWorker with novelty gate, decay replay/gist predicate`

### Task 2（lane2）: 感情 gain + RIF + 分離/補完閾値

**Files（所有）:**
- Modify: `nous/domain/memory/entities.py:181-184`（boost_on_recall 感情 cap）
- Modify: `nous/domain/memory/query_service.py`（RIF 抑制）
- Modify: `nous/domain/search/engine.py:163` 周辺（recall 経路の競合群抽出）
- Modify: `nous/domain/search/ranker.py`（補完モード top-1 許容の閾値調整箇所があれば適用）
- Modify: `nous/infrastructure/sqlite/entity_repo.py`（Hebbian link 作成時の `brain_link_separation_threshold` 適用。emit 規約は既存どおり）
- Test: `tests/unit/test_memory_strength.py`（拡張）、`tests/unit/test_rif.py`（新規）、`tests/unit/test_associative_links.py`（拡張）

**Interfaces（Consumes）:**
- session_config のキー名（lane1 定義済みの名前をそのまま文字列で参照: `brain_emotion_gain_k` / `brain_rif_suppression_rho` / `brain_link_separation_threshold`）。lane1 と並行のため、config 値は `getattr` ベースの安全参照で読み、未定義時はデフォルト値（Global Constraints どおり）にフォールバックすること

**Steps:**

- [ ] 先にテスト（TDD）:
  - `test_emotion_gain_capped`: `boost_on_recall(emotion_intensity=1.0)` でも gain ≤ 1.5 倍（`min(1 + k*i, 1.5)`）。`emotion_intensity=0` で従来どおり 1.5 倍上限に一致
  - `test_rif_suppresses_competitors`: top-K 候補のうち recalled されなかった競合のみ `strength *= (1 - ρ)` で抑制、recalled された記憶は不変
  - `test_rif_respects_floor`: ρ 適用後も strength ≥ min_strength(0.005)、importance 不変
  - `test_link_separation_threshold`: 類似度が `brain_link_separation_threshold` 未満のペアにリンクを作らない
- [ ] `entities.py` `boost_on_recall`: `gain = min(1 + k * emotion_intensity, 1.5)`（k は config から、デフォルト 0.5）。stability 更新は `min(self.stability * gain, 365.0)`
- [ ] RIF: SearchEngine.search の post-filter 後（engine.py:118-133 の後に位置）に、最終 recall 結果から除外された上位 K(=5) 件の候補を競合群として `strength *= (1 - ρ)` を recall あたり 1 回適用（query_service 経由で repo 更新、emit なし）
- [ ] entity_repo.py の Hebbian link 作成（:208-224 周辺）に分離閾値を適用
- [ ] 実行: `pytest tests/unit/test_memory_strength.py tests/unit/test_rif.py tests/unit/test_associative_links.py tests/unit/test_hebbian_wiring.py -q` → 全 PASS
- [ ] Commit: `feat(brain): emotion-capped recall gain, retrieval-induced forgetting, link separation threshold`

### Task 3（lane3）: 脳シミュレーション設定 UI + グラフ発光 + novelty_gate フロント

**Files（所有）:**
- Modify: `nous/api/http/sections/chat/chat_sidebar_memory.py:138`（memory_enrichment セクションを脳シミュレーションセクションへ吸収・置換）
- Modify: `nous/api/http/static/chat/chat-settings.js:314-319,461-466`（load/collect）
- Modify: `nous/api/http/static/chat/chat-core.js:104`（カテゴリマップに `brain_simulation` 追加）
- Modify: `nous/api/http/static/features/graph.js`（SSE 購読 + 発光）
- Modify: `nous/api/http/static/chat/chat-memory-panel.js:328-342`（novelty_gate ラベル・色）
- Modify: `nous/api/http/static/styles/components.css`（`.wiring-kind-novelty_gate` バッジ + 発光用 CSS があれば追加）
- Test: `nous/api/http/static/chat/chat-wiring-feed.test.js`（novelty バッジ）、設定 load/collect の新規テスト、graph flash の新規テスト（`nous/api/http/static/chat/` or `features/` 配下、既存テストパターン踏襲）

**Interfaces（Consumes）:** lane1 の 10 設定キー名（Global Constraints どおり）。`wiring_events.py` の新 kind `novelty_gate`（**wiring_events.py は所有しない**——lane1/2 側で定義済みと想定し、フロントは kind 文字列のみ扱う）

**Steps:**

- [ ] 脳シミュレーション設定セクション実装:
  - `_render_brain_simulation_section()` を新設（既存 `_render_memory_enrichment_section()` を置換・削除）。details タグ + 手書き input、id 規約 `chat-brain-*`
  - 4 サブグループ: 記憶強化（REM）: auto_run checkbox / interval number / batch_limit number。学習ゲート: novelty_sim_threshold / novelty_importance_threshold / novelty_stability_multiplier / emotion_gain_k。想起と忘却: rif_suppression_rho / link_separation_threshold。可視化: graph_flash_enabled checkbox
  - **各項目に ? マークホバー（title 属性）を新規作成**——脳神経科学由来の日本語説明。例: novelty 閾値「海馬-VTAループのドーパミンゲート。既存記憶との類似が低いほど新規と判定され、長期記憶への定着が強まるよ」/ RIF「想起のたびに、手がかりを共有する競合記憶が抑制される（検索誘発性忘却）」/ グラフ発光「シナプス発火イベントを記憶グラフ上で発光表示する」——流用説明は禁止
  - chat-settings.js の load（314-319 パターン）/ collect（461-466 パターン）両方に追記
- [ ] グラフ発光実装（graph.js）:
  - `EventSource('/api/memory/wiring/stream')` 購読（グラフビュー表示中のみ）。onmessage で JSON パース（既存 pushWiringEvent と同構造）
  - **世代トークン契約**: ノード id ごとにタイマー 1 つ（`flashTimers = {}`）、新 flash が旧タイマーを clear して勝つ。flash は `nodes.update({id, color:{background: kindColor}, size: base*1.6})` → 500ms 後に `_data`（graph.js:118-158 で保持済みの元ノード）との差分で復元
  - kind 色: `novelty_gate`（最大パルス・金系）、`replay_fire`（青紫）、`recall_boost`（既存強調）、`link_fire`/`ppr_hit`（既存バッジ色系）
  - `brain_graph_flash_enabled` が false なら購読しない
- [ ] chat-memory-panel.js の kind ラベルに `novelty_gate: "新規性"` + バー色（金系）追加、components.css にバッジ
- [ ] テスト: wiring feed に novelty バッジ表示テスト、settings load/collect 往復テスト、flash の世代トークン（連続 flash でタイマー 1 本化を assert）テスト
- [ ] 実行（**static 配下で**）: `npx vitest run chat/chat-wiring-feed.test.js chat/chat-settings-brain.test.js features/graph-flash.test.js` → 全 PASS（ファイル名は既存パターンに合わせ調整可）
- [ ] Commit: `feat(ui): brain simulation settings section, graph firing animation, novelty badge`

### Task 4（lane4）: gist 変換 + summarizes relation

**Files（所有）:**
- Modify: `nous/application/workers/consolidation_worker.py`（gist 生成の延長）
- Modify: `nous/infrastructure/llm/memory_enricher.py:19,43,191`（`_VALID_RELATION_TYPES` に `summarizes` 追加 + プロンプト）
- Test: `tests/unit/test_consolidation_worker.py`（既存があれば拡張、なければ gist 部分の新規）

**Interfaces（Consumes/Produces）:**
- gist ノード仕様（decay 側の除外述語が依存）: `kind='semantic'` / `source_type='consolidated'`（**既存仕様のまま厳守**——逸脱すると lane1 の decay 除外が外れる）
- 新 relation 型 `summarizes`（エピソード元記憶 → gist ノード方向）

**Steps:**

- [ ] 先にテスト: `test_gist_summarizes_relation`（gist 生成時に元記憶へ `summarizes` relation が張られる）/ `test_gist_node_shape`（kind/source_type が契約どおり）/ `test_relation_type_validation`（enricher が summarizes を受け付ける）
- [ ] `memory_enricher.py`: `_VALID_RELATION_TYPES` に `summarizes` 追加、プロンプト（:43）と説明文を更新
- [ ] `consolidation_worker.py`: gist 生成時に元記憶クラスタの各記憶へ `summarizes` relation を張る（既存 related_keys/derived_from 処理の延長。emit は wiring 規約どおり試みるが失敗非致命）
- [ ] 実行: `pytest tests/unit/test_consolidation_worker.py tests/unit/test_memory_enricher.py -q` → 全 PASS
- [ ] Commit: `feat(brain): gist summarization with summarizes relation type`

---

### 統合フェーズ（orchestrator 実行）

1. 4 レーン結果のマージ・競合確認（session_config キー名・novelty kind の整合）
2. フル GATE: `pytest` 全体 / vitest / ruff check + format / 型チェック / カバレッジ ≥60%
3. #081 REVIEW（独立コンテキスト、diff と契約表を渡す）
4. 実ブラウザ確認（Playwright MCP）: ①脳シミュレーション設定セクションの表示・保存/再読込・? ホバー説明 ②グラフ発光（シナプス発火）の視認 ③wiring フィードの novelty バッジ ④SSE ページなので domcontentloaded + 要素待ち（networkidle 不使用）
5. COMMIT → RECORD → 報告
