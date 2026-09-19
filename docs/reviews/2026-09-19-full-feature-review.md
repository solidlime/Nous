# Nous 全機能棚卸しレビュー — 2026-09-19

対象: 作業ツリー（HEAD 16ccfd34 + 未コミット変更）。バックエンド・フロントエンドの全機能を探索エージェントが全数調査し、主要指摘は実在性を検証した上で分類した。

**ステータス凡例**: ✅修正済み（本レビューで実装・検証済み）/ 🔧対処方針（実装済みの対処の説明）/ 📌意図的保持（根拠を明記して保持）/ ⏳後日対応

---

## 1. 本レビューで解消した回帰・バグ

| 事象 | 原因 | 対処 | ステータス |
|------|------|------|-----------|
| `tests/unit/test_reflection_retrieval.py` 失敗 | テストヘルパ `_mem` が `created_at` を `get_now()` で都度生成 → recency decay（`emotion_decay.py:11` `_compute_recency_decay`、exp(-0.5·日齢)）が秒差で僅差判定し、composite スコア同点のはずの順序が反転 | `_mem` に `created_at: datetime \| None = None` 引数を追加し、両記憶に同一 `fixed = get_now()` を渡して完全同点化。test id の意図（importance 同点 → 記憶作成順）に一致 | ✅ |
| 循環インポートで即死（`nous.domain.search.engine` ↔ `nous.domain.memory`） | `engine.py:9` が `domain.memory.query_service` を import → `domain/memory/__init__.py:12` → `service.py` → `evolution_service.py:14` が `from nous.domain.search.engine import SearchQuery`（部分初期化モジュール） | `evolution_service.py` と `write_service.py` の SearchQuery を使用箇所で遅延 import（探索パス `evolution_service.py:70`、重複チェック `write_service.py`）。import 順依存を排除 | ✅ |
| `introspection.py` 冒頭の 12 シンボル re-export が循環の温床・死に輸出 | Phase 2 分割時の互換維持用（`# noqa: E402, F401`） | 削除し、参照者（テスト6ファイル・`curiosity.py:434`）を直接 import に移行。`curiosity.py` の遅延解決コメントも実態に合わせ更新 | ✅ |

---

## 2. バックエンド指摘一覧

### 2.1 重複ロジック

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| B1 | `_naive()` が `application/chat/introspection.py:509` と `application/workers/enrichment_worker.py` に重複 | introspection 側（None 許容版）を正とし、enrichment_worker 側は非None特化の1行ヘルパに整理して docstring で関係を明記。共有 import だと戻り値型 `datetime \| None` が呼び出し側の型検査を壊すため（mypy +8）この形が最小| ✅（#011バッチ） |
| B2 | sqlite repo の `_row_to_*` 変換パターンが7ファイル9個（`entity_repo.py:450-480` `memory_crud_repo.py:271` `persona_repo.py:302-320` 等） | 各 repo のカラムが異なるため共通化は不正確になる。テーブル→dataclass の共通 mapper は schema 変更リスクが割に合わず | 📌 |
| B3 | qdrant `get_connection_status` 重複（`adapter.py:242` `client.py:121`） | adapter が client の実装を委譲 | ✅（#011バッチ） |
| B4 | `decay_worker.py:262` get_logger を3回 import | モジュール先頭に統一 | ✅（#011バッチ） |

### 2.2 死にコード

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| B5 | `introspection.py:37-52` curiosity 12シンボル re-export | 削除（§1 参照） | ✅ |
| B6 | `migrations.py:149,182,219`・`settings.py:64,221` の pass-only except | debug ログ追加（意図的無視の可視化） | ✅（#011バッチ） |

### 2.3 例外握りつぶし（~200箇所のうち真の無視は19箇所）

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| B7 | `reflection.py:285` bare except pass（洞察取得） | debug ログ追加、挙動は維持 | ✅（#011バッチ） |
| B8 | `entity_repo.py:242`・`engine.py:253` bare except pass | debug ログ追加 | ✅（#011バッチ） |
| B9 | `introspection.py` 13箇所・`use_cases.py` 17箇所・`enrichment_worker.py` 12箇所の except Exception | ワーカーが LLM/DB 失敗で死なない設計として意図的（debug ログ付き）。全箇所を狭い例外型に変えると逆に脆くなる | 📌 |
| B10 | `time_utils.py:78,199` の parse fallback | 日時パースの意図的フォールバック | 📌 |

### 2.4 層違反

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| B11 | domain → infrastructure: `domain/memory/service.py:19-20`（MemoryEnricher, EnrichmentQueueRepository）、`domain/memory/contradiction.py:97`（LLMProvider）、`domain/search/engine.py:24,27,512`（MotThought, get_logger）、`domain/skill.py:22`（get_logger） | TYPE_CHECKING に移せるものは移行。実行時参照（get_logger 等）は logging の抽象を別レイヤに作るコストがコード量に見合わず | 📌（get_logger は実質プロトコル、残存許容） |
| B12 | application → api: `application/chat/curiosity.py:387`（`api.mcp._tools_helpers._emit_tool_called`）、`pipeline/context_loader.py:150`、`pipeline/prepare.py:154`、`tools/builtin.py:10-11` | wiring event の出力先が api 層 SSE に片方向依存。イベントバス抽象を導入すれば解消するが現仕様では1経路のみ | 📌 |

### 2.5 過剰設計

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| B13 | `application/use_cases.py`（567行の AppContext + registry） | DI コンテナだが、persona 毎の状態管理と実質結合している。分割は interconnect が太く、本レビューでは実施せず構造問題として記録 | ⏳ |
| B14 | memory_stats_mixin / memory_version_mixin / memory_aux_repo の Mixin3層 | 1実装だが sqlite repository の巨大化を避ける意図。統合すると1ファイル800行超 | 📌 |

### 2.6 巨大ファイル（500行超）

`introspection.py` ~700行（内省+自発+好奇心）・`use_cases.py` ~780行・`entity_repo.py` ~480行・`domain/search/engine.py` ~580行・`memory_extractor.py` ~730行。

→ 関心単位の分割（好奇心探索の完全分離等）は Phase 2 分割（curiosity.py 抽出）で着手済み。残りは ⏳。

---

## 3. フロントエンド指摘一覧

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| F1 | persona 作成/削除が `static/base.js:290-370`（静的モーダル経路）と `sections/persona.py:101-307`（動的グリッド経路）に二重。検証の結果、実経路は base.js（モーダル form submit）で persona.py の `createPersona()` は未呼び出しの死にJS | persona タブ自体が dashboard から外れており（commit 4c4a66d5「remove dead Analytics, Personas, Import/Export, Admin tabs」）、前セッションの未コミット変更で `sections/persona.py`・`admin.py`・`analytics.py`・`import_export.py` が staged 削除済みだった。**ただし `sections/__init__.py` が削除済みモジュールを import したままパッケージ import が壊れていた** → 本レビューで `__init__.py` の死に import/__all__ を除去し修復。生経路（base.js のモーダル）に一本化を確認 | ✅ |
| F2 | orb 要素（`sections/base.py:152-154`）が CSS で常時非表示、DOM 生成だけ残存 | DOM 生成 + CSS ルール両方削除 | ✅（#011バッチ） |
| F3 | `.toast-container` 二重定義（`components.css:350,539`） | 検証の結果 `:539` は `@media (max-width: 767px)` 内のレスポンシブ上書きで、重複ではなく意図的な差分 | 📌 |
| F4 | `routers/persona/persona_card.py` デッドファイル（card.png 機能削除済み） | 削除 | ✅（#011バッチ） |
| F5 | `chat-history.js:512 cleanup()`・`:95 getChatSessionId()` 未参照 | 検証の結果どちらも生存（`getChatSessionId()` は同7箇所+`core/sse.js:177`+export で使用、`cleanup()` はメッセージ編集クロージャ内で使用）。削除対象ではなく探索レポートの誤検知 | 📌（誤検知として記録） |
| F6 | highlight.js が全タブでロード（`chat_layout.py:103-107`） | 本 SPA は dashboard.py が全タブ HTML をサーバ側で結合し、タブ切替は CSS `.active` のみ。レンダリング時点でアクティブタブという概念が存在しないため条件ロードは不可能。遅延ロードは JS 側改修が必要 | 📌（構造上の制約として記録） |
| F7 | `chat-core.js` の setupChatInputHandler と ...WithObserver が2経路（Observer は5秒 body ポーリング） | 分割の中間生成物。統合は入力ハンドリングの回帰リスクが高い | 📌 |
| F8 | `chat-settings.js ~1440行`・`chat-send.js ~1244行` 等の巨大 JS | 段階分割を ⏳ | ⏳ |
| F9 | `routers/tts.py ~828行`（キャプション LLM + relay + cache がルーター直埋め） | サービス層抽出を ⏳ | ⏳ |

---

## 4. 記憶機能・脳シミュレーションの外部比較

> 出典検証は別途 librarian が一次文献で裏取り済み。詳細は §4.x の各出典参照。

### 4.1 機能対応の判定サマリ

> 出典は全件一次文献で検証済み（2026-09-19 librarian 検証。※印は前回調査からの訂正）。

| Nous 機能 | 外部先行実装（出典） | 判定 |
|----------|-----------------|------|
| ハイブリッド検索（vector+FTS5+RRF+reranker+SA） | RRF 融合はハイブリッド検索のデファクト。Generative Agents（arXiv:2304.03442v2 §4.1）の retrieval は recency・importance・relevance の重み付き**和**:「score=α_recency·recency+α_importance·importance+α_relevance·relevance」（※「積」ではなく線形結合）。MemGPT はベクトル類似のみ | 独自だが妥当。ただし engine 内 RRF→rerank→SA の後に `_search_memories`（`memory_retriever.py:66-95`）が再ランクする二重ランキングは ablation 不能 |
| FSRS 忘却曲線・昇格・archive | MemoryBank（arXiv:2305.10250v3）の記憶更新は Ebbinghaus 曲線（R=e^(-t/S)）+「相対的重要度」調整（※familiarity という語は文献に無し）。MemGPT/GA に減衰機構なし | 文献系より精緻。ただし `entities.py` の strength 9因子中 novelty(0.05×0.5)/confidence(0.10×0.8) はスタブ定数 |
| Hebbian リンク + PPR spreading activation | HippoRAG（arXiv:2405.14831v3）と構造同型: 海馬インデックス理論ベース、LLM による OpenIE triple 抽出で KG 構築、クエリ概念を seed に PPR | 妥当。entity 共起エッジ(w=0.5)と persistent リンクの二重経路は重複 |
| reflection | Generative Agents（arXiv:2304.03442v2 §4.2）: importance 合計が閾値「150 in our implementation」超過でトリガ | 標準。per-turn legacy と periodic の二重実装が負債 |
| enrichment（LLM 評価+関係抽出） | Mem0 / GPT-Mem と同型 | 標準。novelty gate（stability ×2）は演出レベルで効果未検証 |
| entity 抽出 | HippoRAG は LLM triple。Nous は regex + Sudachi | regex は LLM 抽出に品質で劣る（コスト対品質の選択として記録） |
| brain simulation（6テーマ外装） | 各テーマに一次文献 root あり。新規性ゲート＝海馬-VTA ループ（Lisman & Grace 2005, Neuron 46(5):703-713）、感情による固定化＝扁桃体（McGaugh 2004, Annu Rev Neurosci 27:1-28）、他 Anderson 1994 / Diekelmann & Born 2010 / Winocur & Moscovitch 2011 / O'Reilly & McClelland 1994 | 機構は文献に遡れる。パラメータ（ρ=0.05 等）は arbitrary・実測なし |

### 4.2 判定に基づく対処

| # | 指摘 | 対処 | ステータス |
|---|------|------|-----------|
| M1 | 二重ランキング（engine 再ランク vs `_search_memories` composite） | recency/importance は RRFRanker にも存在。統合は検索品質の回帰リスクが高く、評価スイート無しでは安全に実施不能 | ⏳（ablation テストの整備が先決） |
| M2 | `compute_strength_score` のスタブ定数因子（novelty, confidence） | 除去候補だが全記憶スコアに定数バイアスとして乗っているため、除去は順位に影響。評価スイート後に実施 | ⏳ |
| M3 | reflection 二重実装（`maybe_run_reflection` legacy + `ReflectionEngine` periodic） | 廃止統合候補。トリガ条件が異なる（1h間隔+24h窓 vs 24h毎+MIN_MEMORIES=10）ため、利用中の挙動差を確認してから統合 | ⏳ |
| M4 | `_REFLECTION_META_TAG` メタ記憶（タイムスタンプ保存に実記憶を使用） | 検索・統計を汚染。メタ保存先の変更は schema 変更を伴う | ⏳ |
| M5 | RIF（ρ=0.05）・novelty stability ×2・リンク floor 0.5 の根拠薄弱パラメータ | ponytail 注記（ceiling 明記）をコードに追加: `engine.py` `_apply_rif`、`enrichment_worker.py` `_novelty_gate` docstring、`entity_repo.py` upsert_link floor 引数 | ✅（本レビューで実施） |

---

## 5. 検証結果

- unit + integration テスト: **2645 passed**（本レビュー修正後）
- mypy: 352 errors — 変更前後で同数（本レビューで新規ゼロ、全て既存の厳格モード債務）
- ruff: 触ったファイルに新規 violation なし
- `nous.api.http.sections` のパッケージ import が staged 削除と不整合で壊れていたのを修復（§3 F1）
- 探索レポートの誤検知 2件を検証で捕捉（F3 toast-container はメディアクエリ差分、F5 chat-history.js は生存）

---

## 6. 前回指示書（D1-D14）との突合

- 解消済み: D1（chat_sidebar.py 743行→薄レイヤー分割）、D2, D3, D6, D10-D14
- 残存: D4/D5/D8/D9 相当（§2.3 B9・§2.5 B13・§3 F7・F8 に吸収、上表参照）
