# 脳シミュレーション機能拡張 設計書

- 日付: 2026-09-06
- 状態: 承認済み（ユーザー承認 + #081 アーキテクチャ判断済み）
- スコープ: 神経科学由来 6 テーマ + LLM バックグラウンド実行（WebUI 設定可能）+ グラフ発火可視化

## 1. 背景

脳神経科学調査（lib-1、一次文献 8 件）に基づく 6 テーマを nous に実装する。同時に
`session_config.py:72-73` の `memory_enrichment_auto_run` / `memory_enrichment_interval`
が**バックエンド未接続**（UI のみ存在）であることが判明したため、LLM 定期実行の
配線と WebUI 設定を本設計に統合する。

## 2. アーキテクチャ決定（ADR — #081 判断）

### 採用: 3 つの退屈なループ

**賢い統合スケジューラ（BrainScheduler）は作らない。** 既存 2 ワーカーを残置し、
REM 相当の小さな `EnrichmentWorker` を 1 つ追加する。「脳相」は 3 ワーカーの
間隔差として自然に emerge する。

- 棄却理由: Thread は再起動不能（相 start/stop 制御は破綻）、単一スレッド交互は
  SWS の SQLite 書き込みで REM を飢えさせる、失敗ドメイン結合（LLM 障害で decay 停止）、YAGNI。
- 既存: `DecayWorker`（nous/application/workers/decay_worker.py:27、threading.Thread ポーリング）、
  `ConsolidationWorker`（consolidation_worker.py:74、日次）。
- 新規: `EnrichmentWorker`（同構造の thread ワーカー）。

### 棄却

- **FSRS difficulty フィールド新設**: DB migration 要求＋FSRS v6 完全実装なき半端モデル。RIF は strength 抑制で実装する。
- **MemoryStrength への gist 耐性フラグ**: 保存層へのポリシー漏れ（層違反）。decay_worker 側の述語で実装する。

## 3. 機能仕様

### 3.1 EnrichmentWorker（REM 相当・新規）

ファイル: `nous/application/workers/enrichment_worker.py`（新規）

- 設定を読む: `memory_enrichment_enabled` / `memory_enrichment_auto_run` / `memory_enrichment_interval`（死んだ配線の接続）
- **カーソル契約**: 前回実行以降に作成された記憶のみ対象（再実行冪等。LLM コストの無限増殖防止）
- **上限契約**: 1 周あたり N 件（デフォルト 5）で打ち切り
- emit 規約: 既存 `enrich_service.py` の replay_fire emit（try/except + logger.debug）をそのまま流用
- **novelty ゲートを独立ステップで実行**（LLM 不要・ベクトル検索のみ。importance==0.5 ゲートに縛られない）
- 起動経路: `use_cases.py:558-569` の DecayWorker 起動パターンに倣う

### 3.2 テーマ 1: 感情修飾（扁桃体モデル / McGaugh 2004）

- `entities.py:181-184` `boost_on_recall(emotion_intensity)` の gain に感情係数: `gain = min(1 + k * emotion_intensity, 1.5)`（**cap 必須**）
- decay 側: emotion 高 → 減衰緩和係数（こちらも cap 付き）
- 理由: 感情×新規性×gist 耐性の積算で不滅記憶集合が生じるのを cap が束ねる。テストは cap 到達時 assert

### 3.3 テーマ 2: 新規性ゲート（ドーパミン / Lisman & Grace 2005）

- 対象: EnrichmentWorker のカーソル内の新規記憶（作成と検査の間に recall が挟まっても best-effort 許容）
- 条件: ベクトル類似（`contradiction.py:223` の vector search パターン転用）で `max_cosine < novelty_threshold` && `importance >= salience_threshold`
- **空結果は novel**（max_cosine := 0.0。最初の記憶は novel なので正しい）
- 効果: 初期 stability ブースト（×2〜3、設定可能・**作成後 1 回のみ**）
- **新 wiring kind `novelty_gate` を追加**: `wiring_events.py` WIRING_KINDS + フロント kind マップ + CSS バッジ + テスト（replay_fire 前例と同様の 3 ファイル横断）。meta flavor に潰さない——kind は意味論、色・規模・UI 意味が別物のため

### 3.4 テーマ 3: 検索時競合抑制（RIF / Anderson 1994）

- 競合群の定義: 同一クエリの検索結果上位 K 件から実際に recalled されたものを引いた集合（全記憶対象にすると recall のたびに全体摩耗するため厳守）
- 効果: `strength *= (1 - ρ)`（ρ≈0.05、設定可能）。recall あたり 1 回
- 床: `min_strength = 0.005`（settings.py:91）尊重、importance 不変
- difficulty フィールドは使わない（ADR 棄却どおり）

### 3.5 テーマ 4: 分相化（SWS/REM / Diekelmann & Born 2010）

- SWS 相当 = 既存 DecayWorker（低頻度・重い）+ stability 型 replay_fire emit の追加（enrich と同 emit 規約）
- REM 相当 = 新規 EnrichmentWorker（高頻度・LLM）
- 相 start/stop 制御は実装しない（ADR）

### 3.6 テーマ 5: gist 変換（変換仮説 / Winocur 2010）

- `consolidation_worker.py` 拡張: gist ノード生成（既存部分実装の延長。kind='semantic' / source_type='consolidated'）
- 新 relation 型 `summarizes`: `memory_enricher.py:19` `_VALID_RELATION_TYPES` + プロンプト 2 箇所（memory_enricher.py:43、session_config.py:86）。DB は TEXT 制約なしで migration 不要
- decay 耐性: **decay_worker 側の述語** `kind='semantic' AND source_type='consolidated'` で減衰対象から除外（floor フラグは棄却）

### 3.7 テーマ 6: pattern separation / completion（O'Reilly & McClelland 1994)

- link 作成（Hebbian 強化）: 類似度閾値を分離モード（高め・設定可能）に
- recall 手がかり補完: 低い類似度でもトップ 1 許容（完了モード）
- tuning 値はすべて設定として外出し

### 3.8 グラフ発火可視化

ファイル: `nous/api/http/static/features/graph.js`

- wiring SSE（`/api/memory/wiring/stream`、memory.py:333）を購読
- イベントの source/target がグラフ上に存在すれば `nodes.update` で一時発光（色/size）→ 復元
- **世代トークン契約**: ノードあたりタイマー 1 つ、最新 flash が勝つ、同時多発は 500ms で coalesce、復元は保持済み元ノードデータ（`_data`）との差分で書く。0.5 秒ポーリング再描画との点滅レース防止
- kind ごとに色/規模: `novelty_gate` が最大パルス、`replay_fire` は青紫、`recall_boost` は既存強調色系

## 4. WebUI 設定: 「脳シミュレーション」セクション（ユーザー指示）

設定サイドバーに新カテゴリ **脳シミュレーション**（`data-category="brain_simulation"`、1 つの details セクション）を作り、全機能の設定を集約する。

| サブグループ | 項目 |
|---|---|
| 記憶強化（REM） | enrichment 有効/無効、実行間隔、1 周あたり上限件数（auto_run/interval 接続） |
| 学習ゲート | novelty 類似度閾値、novelty ブースト倍率、感情 gain 係数 k（cap は内部固定） |
| 想起と忘却 | RIF 抑制係数 ρ、link 分離閾値 |
| 可視化 | グラフ発光 有効/無効 |

- 既存 `memory_enrichment` セクション（chat_sidebar_memory.py:138）はこのセクションに**吸収・置換**
- 実装パターン: `_render_memory_enrichment_section()` の details タグ + 手書き input を踏襲。load/collect は chat-settings.js:314-319 / 461-466、カテゴリマップ chat-core.js:104 に 1 行追加
- **? マーク（ホバー説明文）を新規作成する**: 各設定項目に脳神経科学由来の日本語説明（例: 新規性閾値 → 海馬-VTA ループのドーパミンゲートの説明）。既存の汎用説明文の流用はしない
- API: per-persona ChatConfig（chat_management.py:206/214）経由

## 5. #011 レーン配分（ファイル所有権は排他・並列実行可）

| レーン | 所有ファイル | 内容 |
|---|---|---|
| lane1 | `workers/`（decay, 新規 enrichment_worker）、`use_cases.py`、`session_config.py` | EnrichmentWorker + 起動経路 + 設定キー（session_config の**唯一の所有者**）。decay に stability 型 replay_fire + gist 除外述語 |
| lane2 | `entities.py`、`query_service.py`、`search/`、`contradiction.py` | 感情 gain（cap 付）、novelty ブーストヘルパー、RIF。recall/strength 意味論の単独所有 |
| lane3 | `chat-settings.js`、`chat_sidebar_memory.py`、`chat-core.js`、`graph.js`、`chat-memory-panel.js`、`components.css`、`wiring_events.py`（kind 追加のみ） | 脳シミュレーション設定 UI（? ホバー含む）+ グラフ発光。**session_config.py は触らない**——lane1 が確定させたキー名を仕様から受ける |
| lane4 | `consolidation_worker.py`、`memory_enricher.py` | gist 化 + `summarizes` relation 型 + プロンプト更新 |

- 横断的変更は仕様記載どおり**そのファイルの所有レーンが**実装する
- レーン間依存はキー名・関数名の契約のみ（コード依存なし）
- テストファイルは各レーンの所有。カバレッジ ≥60%、全レーンで pytest/vitest/ruff/pptype ゲート共通条件を満たすこと

## 6. リスクと緩和

| リスク | 緩和 |
|---|---|
| EnrichmentWorker の LLM コスト | カーソル + 周上限 N 件 |
| novelty 閾値未調整 | 設定値として外出し、テストは閾値境界をカバー |
| 不滅記憶集合（積算耐性） | 感情 gain cap、novelty ブースト 1 回限り、decay 述語は consolidation 産のみ |
| グラフ点滅レース | 世代トークン + 500ms coalesce |
| 幻想発火（既知） | emit 成功フラグ規約（commit 0a59a10b で確立済み）を全新規 emit で踏襲 |

## 7. 検証計画

- pytest 全体 + 新規テスト（emotion cap / novelty 境界 / RIF 床 / gist 耐性述語 / EnrichmentWorker 冪等性・上限）
- vitest（wiring feed + 設定 UI load/collect）
- 実ブラウザ確認（Playwright MCP）: 設定保存/読込、グラフ発光の視認、ホバー説明文
- 型チェック / ruff / format / シークレットスキャン（GATE 標準条件）
