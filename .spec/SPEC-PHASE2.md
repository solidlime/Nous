# SPEC — Phase 2: 記憶システム高度化

> 出典: `.spec/PLAN.md` (2026-07-26) P2-1 / P2-2
> 前提: Phase 1 完了後
> 最終更新: 2026-07-26（P2-2 探索結果反映）

---

## SPEC-2.1: 記憶の階層化 (P2-1)

### 現状分析（探索結果: ses_0642acb57ffeXDjFTgfJoW0IIs）

| 項目 | 状態 | ファイル:行 |
|------|------|------------|
| `kind` カラム | **既存**。`episodic/semantic/procedural/prospective/chat` | `nous/infrastructure/sqlite/schema.py:26` |
| `memory_create` kind パラメータ | **既存**。MCP ツールとして公開済み | `nous/api/mcp/_tools_memory.py:19-81` |
| `memory_search` kind フィルタ | **不在**。`SearchQuery` に `kind` フィールドなし | `nous/domain/search/engine.py:28-45` |
| auto-capture kind 推論 | **不在**。常に `kind='semantic'` で作成 | `nous/application/chat/pipeline/auto_capture.py:176-182` |
| ConsolidationWorker | **既存**。kind を意識しない統合 | `nous/application/workers/consolidation_worker.py` |
| `kind='chat'` | **デッドコード**。`VALID_KINDS` に存在するが未使用 | `nous/domain/memory/entities.py:7` |
| `_smart_search` kind 伝搬 | **欠落**。サブクエリに kind 未伝搬 | `nous/domain/search/engine.py:296-344` |

**結論**: PLAN.md にあった「`memory_type` カラム追加」は不要。作業の焦点は**既存 `kind` の有効活用とギャップ埋め**にシフト。

### 要件

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | SearchQuery kind フィルタ | `SearchQuery` に `kind: str | None` 追加。SQL WHERE 句に反映 | `domain/search/engine.py`, `infrastructure/sqlite/search_repo.py` | S |
| R2 | MCP kind フィルタ公開 | `memory_search` ツールに `kind` パラメータ追加 | `api/mcp/tools.py`, `api/mcp/_tools_memory.py` | S |
| R3 | auto-capture kind 推論 | 日時/場所/人物を含む→`episodic`、事実/知識→`semantic` | `application/chat/pipeline/auto_capture.py` | M |
| R4 | 死にコード整理 | `kind='chat'` を `VALID_KINDS` から削除 | `domain/memory/entities.py` | XS |
| R5 | `_smart_search` kind 伝搬 | サブクエリ構築時に `kind` を引き継ぐ | `domain/search/engine.py:296-344` | XS |
| R6 | kind 別重み付け検索 | 検索意図に応じた kind 重み調整（オプショナル） | `domain/search/ranker.py` | M |
| R7 | auto-capture kind テスト | kind 推論ロジックのユニットテスト | `tests/unit/test_auto_capture_kind.py`（新規） | S |
| R8 | kind フィルタ統合テスト | kind 指定検索の結合テスト | `tests/integration/test_kind_search.py`（新規） | S |

### 実装順序
```
R4 (XS: 死にコード削除) → R1+R2 (S: フィルタ追加。並列可) → R5 (XS: 伝搬修正)
→ R3 (M: auto-capture 推論) → R7+R8 (S: テスト)
→ R6 (M: 重み付け。Phase 2 後半 or Phase 3 に繰り越し可)
```

### 制約
- 後方互換: 既存の `kind='semantic'` データ多数。migration 不要。
- `memory_create` の kind デフォルトは `"semantic"` を維持。
- `kind` フィルタ未指定時は全 kind を対象（現状と同じ挙動）。
- `kind='prospective'` は既に使用中（未来予定・目標記憶）。変更・削除禁止。

---

## SPEC-2.2: 感情モデル高度化 (P2-2)

### 現状分析（探索結果: ses_0642a8f32ffeaL8ry9QWvKIdS7）

**コア発見**: `PersonaState` は単一感情モデル。`drive` は存在しない。減衰パラメータは全ハードコード。複数感情化は 17 ファイルに影響する大規模変更であり、段階的アプローチが必須。

**重要**: PLAN.md の「複数感情共存」はコスト対効果が悪く、Phase 2 ではなく Phase 5（長期ビジョン）に繰り越す。Phase 2 では「減衰パラメータ設定化」と「感情伝播」に集中する。

### Step 1: 減衰パラメータ設定化 + emotion_history 修正 (P2-2a)

**対象**: ハードコードされた減衰値を config 化 + DB バグ修正

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R1 | 減衰パラメータ config 化 | `half_life_hours` (default 24.0), `threshold` (default 0.005), `neutral_floor` (default 0.01) を `ProviderConfig` に追加 | `domain/provider_config.py`, `domain/persona/emotion_decay.py` | S |
| R2 | decay config 伝播 | `PrepareStep` → `_apply_emotion_decay()` に config を渡す | `application/chat/pipeline/prepare.py`, `api/mcp/_tools_helpers.py` | S |
| R3 | emotion_history に persona カラム追加 | テーブルに `persona TEXT NOT NULL` 追加。migration v5。既存の `idx_emotion_history_persona` が有効化 | `infrastructure/sqlite/schema.py`, `infrastructure/sqlite/migrations.py` | M |
| R4 | persona_repo 修正 | `add_emotion_record()` で persona カラムを含めた INSERT | `infrastructure/sqlite/persona_repo.py:148-170` | S |
| R5 | WebUI 設定追加 | 減衰パラメータをチャット設定 UI に追加 | `api/http/static/chat/chat-settings.js`, `api/http/sections/chat/chat_sidebar_core.py` | S |
| R6 | 感情履歴可視化 | Overview タブに感情推移グラフを追加（既存 API あり） | `api/http/static/features/overview/overview-charts.js` | M |

### Step 2: 感情伝播 (P2-2b)

**対象**: 会話中の感情が後続発言と記憶に波及する仕組み。P2-2a 完了後に着手。

| # | 要件 | 内容 | 変更ファイル | 規模 |
|---|------|------|-------------|------|
| R7 | 感情トリガーワード | 辞書ベースの感情変動（「猫」→ joy、「試験」→ anxiety）。`persona/config.json` に `emotion_triggers` 追加 | `domain/persona/emotion_triggers.py`（新規）, `data/persona/*/config.json` | M |
| R8 | トリガー検出パイプライン | `PrepareStep` でユーザー発言をトリガー辞書とマッチング、感情微調整 | `application/chat/pipeline/prepare.py` | S |
| R9 | メモリ感情自動付与 | `create_memory()` 時に現在のペルソナ感情を自動付与 | `domain/memory/write_service.py` | S |
| R10 | 感情一致度ランキング | `EmotionRecallBiasRanker` に現在感情と記憶感情の一致度加点 | `domain/search/ranker.py` | M |
| R11 | EmotionDrivenSampler 全感情対応 | 未登録の 11 感情を `_EMOTION_MODIFIERS` に追加 | `domain/sampling.py:26-54` | S |
| R12 | 感情伝播テスト | トリガー検出・伝播のユニットテスト | `tests/unit/test_emotion_triggers.py`（新規） | S |

### Step 3: 複数感情共存 — Phase 5 に繰り越し

**理由**: 17 ファイル（DB スキーマ / MCP ツールシグネチャ / PersonaState 型 / context_state 永続化 / プロンプト生成 / SSE イベント）すべてに影響する大規模変更。コスト対インパクトが悪く、まず単一感情モデルを最大限活用すべき。

### Step 4: 神経伝達物質モデル — Phase 5 に繰り越し（Mímir 路線）

### 実装順序
```
Phase 2 前半:
  P2-2a R1+R2 (S: decay config化) → R3+R4 (M: emotion_history fix + migration)
  → R5 (S: WebUI) → R6 (M: 可視化)
  （P2-1 と並列実装可能。変更ファイルの重なりは prepare.py のみ→順序調整で対応）

Phase 2 後半:
  P2-2b R7+R8 (M+S: トリガー) → R9 (S: メモリ自動タグ) → R10+R11 (M+S: ランカー+Sampler)
  → R12 (S: テスト)
```

---

## 実装方針（Phase 2 全体）

| 項目 | 方針 |
|------|------|
| 並列度 | P2-1 と P2-2a は **並列可能**（変更ファイルの重なりは `prepare.py` のみ→順序で吸収） |
| 調査 | #009 explorer ×2（P2-1 系 / P2-2 系） — 本スペック作成時に完了 |
| 実装 | #011 fixer をタスク粒度でディスパッチ。ファイル群が独立なら並列投入 |
| テスト | `pytest -x -q` で対象ファイル指定実行（メモリ制約）。フルスイート禁止 |
| コミット | タスク単位で atomic commit |
| 依存 | P2-2b は P2-1 R3（auto-capture kind 推論）完了後に着手（トリガー→kind 連携のため） |
