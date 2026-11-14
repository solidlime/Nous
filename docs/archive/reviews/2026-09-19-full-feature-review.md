# Nous 全機能棚卸しレビュー — 2026-09-19

対象: 作業ツリー（HEAD 16ccfd34 + 未コミット変更）。バックエンド・フロントエンドの全機能を探索エージェントが全数調査し、主要指摘は実在性を検証した上で分類した。

**ステータス凡例**: ✅修正済み（本レビューで実装・検証済み）/ 🔧対処方針（実装済みの対処の説明）/ 📌意図的保持（根拠を明記して保持）/ ⏳後日対応

**修正ラウンド**: 本レビューは 3 ラウンドで完結している。

| ラウンド | 内容 | 主要コミット |
|---|---|---|
| 1 | 静的解析ベースの全数レビュー+修正（本書 §1-§3, M1-M5） | — |
| 2 | 脳シミュレーション配線の実機検証 → RankPolicy 統合・reflection 統合・スタブ因子除去・互換バグ修正 | `6d755496` `e7d39f4f` `a151c16a` `0631d8bc` `a3f2c470` |
| 3 | フロントエンド JS 巨大ファイル分割・AppContext 分割・全残課題（format/lint/TZ）解消・実機機能検証 | `e67bf9fd` `ad97b20b` `00383e4b` |
| 4 | memory_search の CJK 連結クエリ空ヒット修正（FTS Sudachi 形態素化） | 本ラウンド |

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
| B13 | `application/use_cases.py`（567行の AppContext + registry） | ラウンド 3 で実施: 状態遷移/ベクトルスタック/イベント配線を `nous/application/context/{lifecycle,vector_stack,event_handlers}.py` ミックスインに分離（-337 行、use_cases.py は 487 行に）。`AppContext` の公開 API は不変（MCP/WebUI 両経路の互換維持） | ✅（`00383e4b`） |
| B14 | memory_stats_mixin / memory_version_mixin / memory_aux_repo の Mixin3層 | 1実装だが sqlite repository の巨大化を避ける意図。統合すると1ファイル800行超 | 📌 |

### 2.6 巨大ファイル（500行超）

`introspection.py` ~700行（内省+自発+好奇心）は Phase 2 分割（curiosity.py 抽出）で解消済み。`use_cases.py` は B13 で解消済み。残る巨大ファイル: `domain/search/engine.py` ~580行（検索パイプライン単機能で凝集度高・分割はインターフェース増Only）と `memory_extractor.py` ~730行（抽出プロンプト群の塊）は 📌 保持。

### 2.7 検証で判明した互換バグ（ラウンド 2）

| # | 事象 | 対処 | ステータス |
|---|------|------|----------|
| B15 | `VALID_SOURCE_TYPES` に `system` が無く、システム生成記憶（reflected 等）の書込が `ValueError` で落ちる | `domain/memory/entities.py` に `"system"` を追加 | ✅（`0631d8bc`） |
| B16 | `persona_repo.get_emotion_history()` / `get_emotion_history_by_days()` に `WHERE persona = ?` が無く、全ペルソナの感情履歴が混在する | 両メソッドに persona フィルタ追加 | ✅（`0631d8bc`） |
| B17 | `memory_search` で助詞なし CJK 連結クエリ（例: 「量子テレポーテーション実験」）が空ヒット — FTS5 `unicode61` が CJK 連続を 1 トークン扱いするため形態素単位のクエリが raw インデックスと絶対に一致しない | ラウンド 4 で実施: インデックス側（`memory_crud_repo` 保存/更新後に `memories_fts` を再トークン化）とクエリ側（`_sanitize_fts_query` で形態素 AND 展開）の両面を Sudachi 表層トークンで統一（`fts_tokenize.py` 新設、辞書欠落時は raw フォールバック）。既存 DB は v10 マイグレーションで再トークン化。実機: 連結/分かち書き/単語クエリ全て HIT を確認 | ✅ |

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
| F8 | `chat-settings.js ~1846行`・`chat-send.js ~1532行`・`chat-history.js ~1025行`・`chat-memory-panel.js ~1133行` の巨大 JS | ラウンド 3 で実施: 4 ファイルを 17 チャンク（全て ≤500 行）のサブモジュールに分割し、ファサード 4 本（11-12 行）で既存参照経路を維持。内部共有は `N.Chat._send` / `N.Chat._history` / `memoryPanel._wiring` 名前空間テーブル。挙動同等修正は `clearWiring()` の配列参照維持のみ。vitest+jsdom（277 テスト）を同時導入 | ✅（`e67bf9fd` `ad97b20b`） |
| F9 | `routers/tts.py ~825行`（キャプション LLM + relay + cache がルーター直埋め） | 📌 保持。根拠: (1) テスト契約が遅延バインディング — `test_tts_stream_endpoint.py:84-86` が `monkeypatch.setattr(tts_mod, "_safe_get_context"/"get_voice_engine"/"take_caption_task", ...)` で tts モジュール属性を差し替え、ハンドラ内部がそれをモジュールグローバル解決するため、分割すると循環 import 回避の遅延経路が必要になる (2) 機能は単一（5 エンドポイント+キャプション 2 モード+キャッシュ）で凝集度高 (3) 挙動変化ゼロの割に 9 テストファイルにまたがる回帰リスク。分割する場合は純粋関数群（caption 構築・cache key 生成）から段階的に | 📌 |

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
| M1 | 二重ランキング（engine 再ランク vs `_search_memories` composite） | ラウンド 2 で実施: 複合スコアリング（recency+importance+relevance+reflection penalty）を `SearchEngine` 最終段の RankPolicy に一本化。`application/chat/pipeline/memory_retriever.py:50` は 2 クエリ並列検索+key dedupe（max score 採用）のみに縮退。単体 15 件+統合テストでスコアリング契約を固定 | ✅（`6d755496` `e7d39f4f`） |
| M2 | `compute_strength_score` のスタブ定数因子（novelty, confidence） | ラウンド 2 で除去。実機で同記憶の再検索による強化（0.572→0.707）を確認（§8.1） | ✅（ラウンド 2） |
| M3 | reflection 二重実装（`maybe_run_reflection` legacy + `ReflectionEngine` periodic） | ラウンド 2 で統合: legacy per-turn 経路を廃止し periodic のみに。`application/chat/reflection.py` は移転注記のみ、実行経路は `decay_worker.py:244 _maybe_run_reflection` に一本化。UI から `reflection_interval_cycles`（`a151c16a`）で周期調整可 | ✅（`a3f2c470`） |
| M4 | `_REFLECTION_META_TAG` メタ記憶（タイムスタンプ保存に実記憶を使用） | M3 統合で廃止。`_REFLECTION_META_TAG` のコード内参照は消滅（grep で確認済み） | ✅（`a3f2c470`） |
| M5 | RIF（ρ=0.05）・novelty stability ×2・リンク floor 0.5 の根拠薄弱パラメータ | ponytail 注記（ceiling 明記）をコードに追加: `engine.py` `_apply_rif`、`enrichment_worker.py` `_novelty_gate` docstring、`entity_repo.py` upsert_link floor 引数 | ✅（本レビューで実施） |

---

## 5. 検証結果（最終）

- unit テスト: **2477 passed** / integration: **167 passed**（計 2644、失敗 0）
- mypy: **339 errors** — HEAD ベースラインと同数（本レビュー全ラウンドで新規ゼロ）
- ruff check: **0 violations**（全ツリー）/ ruff format: **449 ファイル全て準拠**（ラウンド 3 で既存ドリフト 30 ファイルを整形）
- vitest+jsdom: **277 passed**（TZ 未指定環境で実施 — テスト内 ISO タイムスタンプに明示オフセット `+09:00` を付与し TZ 独立化。`chat-monologue.test.js`）
- `nous.api.http.sections` のパッケージ import が staged 削除と不整合で壊れていたのを修復（§3 F1）
- 探索レポートの誤検知 2件を検証で捕捉（F3 toast-container はメディアクエリ差分、F5 chat-history.js は生存）
- 実機検証（§8）: テストサーバー :26262 で全 MCP ツール・WebUI 全タブを操作し期待どおり

---

## 6. 前回指示書（D1-D14）との突合

- 解消済み: D1（chat_sidebar.py 743行→薄レイヤー分割）、D2, D3, D6, D10-D14
- 残存: D4/D5/D8/D9 相当（§2.3 B9・§2.5 B13・§3 F7・F8 に吸収、上表参照）
