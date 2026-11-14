# REM アイドル駆動化・脳用LLM設定・モーダル統合 設計書

- 日付: 2026-09-06
- 状態: 口頭承認済み（トグル向き修正 `brain_llm_dedicated` は本書に反映済み）
- スコープ: (A) 脳シミュレーション（REM 相当 enrichment）トリガーのアイドル駆動化、(B) 脳シミュレーター用 LLM 設定 UI、(C) メモリ詳細モーダル統一、(D) 重複実装解消フェーズ1

## 1. 背景

- 現状の enrichment トリガーは二重払い: `memory_create` 時の即時バックグラウンド LLM（`nous/domain/memory/service.py:204-213`）+ `EnrichmentWorker` 60s ポーリング（`nous/application/workers/enrichment_worker.py:76-97`）。`importance==0.5` の記憶は二重課金（`nous/domain/memory/enrich_service.py:45`）。
- `memory_read` / `memory_search` は脳シミュレーターを起動しない（`nous/api/mcp/_tools_memory.py` — read は boost_recall + 共アクセス記録のみ、search は両方無し）。
- 脳シミュレーター用 LLM は裏側で既に分離済み（`nous/config/settings.py:96-104` `MemoryEnrichmentConfig`、解決点は `nous/application/use_cases.py:185-217` `_init_enricher` のみ）だが、WebUI 設定が無い。
- メモリ詳細表示が 4 箇所で別実装（Memories モーダル / Chat wiring 詳細 / Graph サイドパネル / Timeline パネル）。バー描画・esc・日付・SSE 接続・委譲も重複（#009 監査、確実リスト 7 件）。

### 根拠調査（lib-1 / exp-1 サマリ）

- 神経科学: 記憶固定（replay）は符号化後数分〜数時間〜オーバーナイト。即時でも日単位放置でもない。「静覚醒（会話の合間の静寂）」も固定窓。Dudai 2015, Neuron。
- 先行技術: Generative Agents=重要度累積、Letta/MemGPT=N ステップ駆動、Sleep-time Compute (arXiv:2504.13171)=アイドル駆動でテスト時 compute 約 5 倍削減。**60s 固定ポーリングを採る先行例は無い**。
- コスト実測: 1 コール ≈ 950〜1,500 in / 50〜200 out トークン。デフォルト `openai/gpt-4o-mini` で 1 コール約 0.06 円、実使用量（herta DB: 記憶 2〜13 件/日 + read 2〜3 件/日）で **月 6〜15 円**。コストは決定要因ではない。

## 2. ユーザー決定

| 決定 | 内容 |
|---|---|
| トリガー方式 | **アイドル駆動ハイブリッド**（読み書きはキューに積むだけ、アイドル時にバッチドレイン、1 時間で強制実行、60s ポーリング廃止） |
| 読み取りトリガー | memory_read/search も処理対象にする |
| モーダル統一範囲 | メモリ詳細は全て Memories モーダルへ。Graph entity 表示はサイドパネル維持 |
| 脳用 LLM トグル | **OFF=デフォルトでチャット設定を流用（項目非表示）、ON=専用設定（項目表示）**。キー名は `brain_llm_dedicated` |
| 重複解消スコープ | 確実リストのうち SSE/esc/バー/日付/モーダル開閉/委譲。fetch・toast・直 new・mypy は棚卸しに記録して次回 |

## 3. A: REM アイドル駆動化

### 3.1 永続キュー（#081 レビュー反映: dedupe 設定）

- 新テーブル `enrichment_queue`（memory.sqlite）: `id`, `memory_key`, `enqueued_at`, `processed_at`（NULL=未処理）。`event_type` 列は作らない（処理が type で分岐しないため YAGNI）。
- **一意制約で dedupe**: 部分一意インデックス `ux_enrichment_queue_pending ON enrichment_queue(memory_key) WHERE processed_at IS NULL`。enqueue は `INSERT OR IGNORE`。DDL は `nous/infrastructure/sqlite/schema.py` に追加。
- `memory_create`: `service.py:204-213` の即時 `enrich_memory` バックグラウンドタスクを廃止 → enqueue のみ。
- `memory_read` / `memory_search`: boost_recall（read のみ現状・**boost はヒット先頭 10 件に cap**）＋ record_memory_access（**search はヒット上位 `min(3, len(hits))` 件のみ**に限定——co-access 窓 20 件の撹乱防止）を呼び、かつ未 enrich の memory を enqueue。
- **drain 側 dedupe**: worker は `SELECT DISTINCT memory_key WHERE processed_at IS NULL` で取得、memory 単位で 1 回だけ enrich。同一 memory_key の processed 行が既にあれば再 enrich しない（read トリガーでの再課金を構造的に排除。processed 履歴が永続的な enrich 済みマーカーになり、現行 `_processed_keys`（enrichment_worker.py:48）の「メモリ上のみ・再起動で消失」問題を同時に解消する）。
- 処理完了後に processed マーク＝シャットダウンで喪失なし。

### 3.2 EnrichmentWorker 変更

- スレッド構造は維持（T072 設計書 §3.1 の ADR を踏襲）。`brain_enrich_interval_seconds` は**キュー監視間隔**に降格（軽量 DB チェックのみ、LLM 呼び出しは含まない）。
- **アイドルゲート**: 源は `session_events` テーブル（`SELECT MAX(timestamp) FROM session_events WHERE persona = ?`、既存インデックス `idx_session_events_persona` で軽量）。経過秒 ≥ `brain_idle_after_seconds`（デフォルト **120**）でドレイン開始。`_session_event_repo` が None の場合は**アイドル未達として扱う**（`max_defer_seconds` 超過分だけは例外として強制ドレイン）。
- **最小バッチ**: 未処理 < `brain_min_batch_size`（デフォルト **3**）なら待機。
- **飢餓対策**: `enqueued_at` から `brain_max_defer_seconds`（デフォルト **3600**）経過したイベントがあればアクティブ中でも強制ドレイン。
- novelty ゲート（ベクトルのみ・LLM 不使用）とカーソル契約は維持。キュー導入後は「キューに create イベントがある記憶」が主対象。
- バッチ coalesce（複数記憶を 1 LLM コール化）は**スコープ外**（prompt 変更が要る。棚卸しに記録）。

### 3.3 併せて直す（小規模）

- `nous/infrastructure/llm/memory_enricher.py:124-131`: `_call_llm` が `DoneEvent.usage` を破棄 → **戻り値 `(text, usage)` 化して上流へ渡す**（インスタンス属性保持は禁止——`enrich_async` は background task と worker スレッドから並行呼び出され競合する）。`enrich_service` で INFO ログ + `replay_fire` meta に usage を含め実測トークンを可視化。
- `enrich_service.py:46` の `contextlib.suppress(Exception)` による LLM 失敗の黙殺: 失敗を debug ログに残す（二重課金と失敗の区別が付く最低限のみ）。

## 4. B: 脳シミュレーター用 LLM 設定

### 4.1 設定キー（per-persona）

`nous/domain/session_config.py:95-104` の brain_* 群に追加（ChatConfig フラット分配 `chat_config.py:175-186` は自動追随）:

- `brain_llm_dedicated: bool = false` — **OFF=チャット設定を流用、ON=専用設定**
- `brain_llm_provider: str = ""`, `brain_llm_model: str = ""`, `brain_llm_base_url: str = ""`, `brain_llm_api_key: str = ""`

### 4.2 解決（一点のみ）

`use_cases.py:185-217` `_init_enricher`（#081 レビュー反映）:

- `cfg is None`（ChatConfig 無しの MCP 起動等）→ **現行の `settings.memory_enrichment` 鎖を維持**（トグル OFF の意味は「cfg がある時に chat 鎖を使う」に限定）
- `brain_llm_dedicated == false`（cfg あり）→ チャットの **provider/model/base_url/api_key の 4 点セット**を `cfg.provider_config` の `get_effective_*` チェーン経由で使用（provider だけ混合しない）
- `== true` → `brain_llm_*` を使用。空フィールドは既存フォールバック鎖（`settings.memory_enrichment` → RuntimeConfigManager → レガシー env）に落とす
- チャットキーの最終フォールバックは **brain provider == chat provider の場合のみ**適用。異種プロバイダなら enricher 生成を止め（enrichment 無効）＋ debug ログ（キー混用防止）
- **再解決フック**: 設定保存後に enricher を再生成（`chat_management` の config 保存ルートから ctx 経由で `_init_enricher` を再実行）し、稼働中のトグル切替を即時反映。実ブラウザ検証にトグル切替後の反映確認を含める

### 4.3 WebUI

- `nous/api/http/sections/chat/chat_sidebar_memory.py:159-232`（`_render_brain_simulation_section`）にトグルスイッチ「脳シミュレーター専用 LLM を使う」＋ OFF 時は非表示、ON 時に provider/model/base_url/API キー項目を表示。
- load/collect は `nous/api/http/static/chat/chat-settings.js`（load :314-329 / save :472-484）。契約テスト `chat-settings-brain.test.js` を拡張。
- ラベル文言・トグル見た目は #057 に委譲（本書は構造のみ規定）。

## 5. C: メモリ詳細モーダル統一

正 = `features/memories/memories-edit.js:33-148` `openMemModal`（`openMemModalByKey(key)` で API 取得後表示）。

| 画面 | 変更 |
|---|---|
| Timeline (`features/timeline.js:161-207`) | アイテム選択 → `openMemModalByKey(key)`。`#tl-detail-panel` と手書き body bars（:174-195）を削除 |
| Graph (`features/graph.js:437-530`) | メモリノード select → `openMemModalByKey`。graph 側の memory 表示ブランチ・手書き importance バー（:509-520、safeSetHTML で style が消える潜在バグごと）を削除。entity ブランチはサイドパネル維持 |
| Chat wiring (`chat/chat-memory-panel.js:883-994`) | エッジ詳細モーダルは存続（source→target/weight/kind は別機能）が、バー/タグ/日付描画を共通コンポーネント経由に置換。行から対象 memory_key で mem モーダルを開く導線を追加 |

## 6. D: 重複実装解消（フェーズ1）

1. **SSE 接続統合**: `chat/chat-memory-panel.js:728-810` `connectWiring` と `features/graph.js:114-135` `connectGraphFlash` を `core/sse.js`（`connectSSE`）に統合。graph 版は再接続（backoff）挙動を core に合わせる
2. **esc 統一**: `chat-memory-panel.js:360-367` `_wiringEscAttr` 削除 → `core/dom.js` `N.Core.esc`
3. **バー描画集約**: importance/emotion/body_state バーは `components/memory-card.js:56-104`（`renderBodyStateBars` / `renderEmotionBars` / data-fill 機構）に集約
4. **日付集約**: `core/time.js` に完全日時バリアントを追加し、`timeline.js:169` / `activity.js:173,213` / `memories-edit.js:110,115,120` / `chat-memory-panel.js:931,935` の手書き toLocaleString を置換
5. **モーダル開閉のクラス方式統一**: `overview-inventory.js:23-76` / `overview-core.js:198-240` / `base.js:543-580`（persona モーダルの JS で DOM 自作）を `ov-modal-overlay` + クラストグルに寄せる（#057 レーン）
6. **委譲統一**: `chat-memory-panel.js:997-1019` の自前 document 委譲（`data-wiring-*`）を `core/delegation.js` に移設
7. **ID/クラス混在解消**: `memories-edit.js:34-54` の `#mem-modal-content` と `.mem-modal-content` を整理

## 7. 棚卸し（スコープ外・今後の解消対象）

| # | 対象 | 場所 | 内容 | 優先度 |
|---|---|---|---|---|
| 1 | `ChatConfigFileRepository` 直 new | `routers/tts.py:111,470,590,705`, `routers/chat/chat_stream.py:10`, `chat/chat_management.py:11`, `routers/events.py:55`, `routers/image_gen.py:51`, `domain/memory/query_service.py:35` 他計 10+ | DI(ctx) 経由に統一 | 中 |
| 2 | 生 `fetch` 迂回 | `chat-history.js:71,311,868`, `chat-settings-image.js:39,71`, `chat-send.js:346,423`, `base.js:362` 等 | `N.Core.api` に置換（バイナリ/ストリーム用途は対象外） | 中 |
| 3 | ネイティブ `confirm()` | `overview-inventory.js:14` | `N.Components.modal.showConfirm` に統一 | 低 |
| 4 | 80 字 cut 手書き | `chat-memory-panel.js:41,93,153,191` | `N.Core.truncate` と統一 | 低 |
| 5 | mypy 既存エラー | `enrich_service.py:56,82`, `use_cases.py` 各所, `decay_worker.py:121` | Protocol 化等 | 低 |
| 6 | バッチ coalesce | enrich prompt | 複数記憶の 1 コール化 | 低 |

## 8. テスト・検証

- pytest: キュー永続化（processed マーク・再起動再開）、アイドルゲート/最小バッチ/強制ドレイン、トグル解決（ON/OFF × フォールバック鎖）、search での boost/共アクセス。
- vitest: chat-settings-brain 契約拡張、モーダル統一（mem モーダル開閉・graph/timeline からの起動）、delegation 移設。
- **実ブラウザ検証（必須）**: Playwright MCP で全タブのメモリ詳細表示、脳用 LLM トグルの表示切替、wiring SSE 接続（readyState 1）を確認。networkidle は待たない（domcontentloaded + 要素待ち）。
- GATE: 型/テスト 0 失敗/カバレッジ ≥60%/lint 0/format/シークレット 0。

## 9. レーン構成（実装時）

1. #081 設計レビュー（実装前アーキテクチャ判断）
2. バックエンド #011: §3（キュー・worker・usage 記録）+ §4.1-4.2（キー・解決）
3. フロント #057 + #011: §4.3（UI）+ §5 + §6（C/D は UI 主体、#057 が設計主導、機械的置換は #011）
4. 検証ループ → #081 REVIEW → GATE → COMMIT → RECORD
