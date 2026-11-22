# Memory Features

This document describes the advanced memory management features.

---

## Forgetting Curve (retired 2026-11-08)

FSRS v6 power-law decay was removed together with `DecayWorker`. Memories are no longer
aged out by time: the only ways a memory leaves `active` are wiki compilation and
consolidation (`lifecycle_status` `active` → `archived`). Search ranking no longer
reads any strength/recall score.

The `memory_strength` table and its rows are kept as history only — nothing writes to
them any more, so the values are frozen at whatever the last decay cycle computed.

---

## Bi-temporal User State Tracking

User information fields (`name`, `nickname`, `preferred_address`) are stored with full temporal history. Instead of overwriting values, each change is recorded with `valid_from` / `valid_until` timestamps.

### Schema

```sql
CREATE TABLE user_state_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    persona     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    valid_from  TEXT NOT NULL,
    valid_until TEXT DEFAULT NULL,  -- NULL means "currently valid"
    created_at  TEXT NOT NULL
);
```

### Usage

```python
# Get current state
state = get_current_user_state("herta")
# → {"name": "らうらう", "nickname": "らう", ...}

# Full history for a key
history = get_user_state_history("herta", "name")
# → [{"value": "らうらう", "valid_from": "...", "valid_until": None, "is_current": True}, ...]
```

When `update_context(user_info={"name": "..."})` is called, the current record is invalidated and a new one is inserted atomically.

---

## Memory Evolution (A-MEM Pattern)

新しく記憶が作成されたとき、意味的に類似する既存の記憶を検出して自動的に更新する仕組みです。[A-MEM](https://arxiv.org/html/2502.12110) の「各事実が既存の理解を継続的に洗練させる」パターンを実装しています。

### 動作

1. `MemoryService.create_memory()` が完了した後、`asyncio.create_task` で非同期・非ブロッキング実行
2. 意味検索（semantic search, `similarity ≥ 0.8`）で類似する既存記憶を最大3件検出
3. 検出された各記憶に対して:
   - **アクセス更新**: `access_count` 増加、`last_accessed` 更新
   - **Hebbian リンク強化**: 新記憶と既存記憶の間に `SEMANTIC` タイプのリンクを作成・強化
   - **`summary_ref` 設定**: 既存記憶に関連する新しい情報があることをマーク

### 重要な特性

- **非同期・ノンブロッキング**: `asyncio.create_task()` で実行され、ユーザー応答を遅延させない
- **ベストエフォート**: 例外はすべて `try/except` で吸収され、メインの記憶作成フローには影響しない
- **条件付き実行**: コンテンツ長が30文字未満の場合はスキップ（ノイズ記憶を進化させない）

### 既存の重複排除との関係

保存時の重複排除（`similarity > 0.85`）は進化より**前に**実行されます。つまり、重複と判定されるほど近い記憶は保存自体がスキップされ、進化の対象にはなりません。進化が扱うのは `0.8 ≤ similarity ≤ 0.85` の「関連はしているが重複ではない」記憶です。

---

## LLM Summary Compaction (Stage 3')

`CompressStep` は予算超過時に、会話の head から node 単位で永続 evict し、落とした切片を LLM で要約して `history_summary` に積みます（履歴は append-only で、要約は差分として追記される）。

### 動作

1. **トリガー条件**: 以下のすべてを満たす場合のみ実行
   - `context_use_llm_summary = True`（デフォルト: `True`）
   - APIキーが設定されている
   - Stage 1（古いツール結果のステータス置換）後もコンテキストが予算超過
   - 切片に user 発言が含まれる
2. active path の head から user 境界で node 単位に evict（1回の要約に載せるのは最大60メッセージ）
3. LLM で差分要約を生成し、既存の `history_summary` に追記（全体 4000 文字上限、超過分は古い方から削る）
4. 要約は次ターンの揮発ブロック（`[NOUS CONTEXT]`）として送信される

### 設定

| 設定キー | デフォルト | 説明 |
|---|---|---|
| `context_use_llm_summary` | `True` | Stage 3' の有効/無効 |

チャット設定パネルからも切り替え可能。

### フォールバック

LLM 呼び出しが失敗した場合（ネットワークエラー、レート制限など）は、機械的圧縮の結果をそのまま使用します。要約失敗がユーザー体験に影響することはありません。

---

## Bi-temporal Validity Windows (Graphiti 着想)

記憶に有効期間（validity window）を導入し、時間的に矛盾する情報を「上書き」せず「共存」させます。[Zep/Graphiti](https://github.com/getzep/graphiti) の bi-temporal model に着想。

### データモデル

```python
@dataclass
class Memory:
    valid_from: datetime | None = None  # 記憶が有効になった日時
    valid_until: datetime | None = None  # None = 現在も有効
```

| 値 | 意味 |
|---|---|
| `valid_from = None, valid_until = None` | 時間制限なしで常に有効（後方互換、デフォルト） |
| `valid_from = 2024-03, valid_until = 2025-06` | この期間のみ有効 |
| `valid_until = now()` に設定 | 無効化（論理削除、矛盾する新しい記憶で上書き時） |

### 自動無効化（矛盾検出時）

新しい記憶が既存の記憶と矛盾する場合（semantic similarity ≥ threshold かつ 3-op 分類で CONTRADICTORY）、古い記憶の `valid_until` が自動的に新しい記憶の `created_at` に設定されます。非同期（`asyncio.create_task`）かつ best-effort。

### 検索フィルタリング

`SearchQuery.valid_at` を指定することで、特定の時点で有効な記憶のみを取得可能:

```python
SearchQuery(text="...", valid_at=datetime(2024, 6, 15))
# → valid_from <= 2024-06-15 AND (valid_until IS NULL OR valid_until > 2024-06-15)
```

`valid_at=None`（デフォルト）では全件返却。後方互換を完全維持。

### マイグレーション

v037: `ALTER TABLE memories ADD COLUMN valid_from TEXT; ADD COLUMN valid_until TEXT;`

---

## 3-op Contradiction Classification (HiMem 着想)

矛盾を「検知するだけ」から「分類して適切に処理する」に拡張。[HiMem](https://arxiv.org/html/2601.06377) の reconsolidation パターンに準拠。

### 3分類

| 分類 | 動作 |
|---|---|
| **INDEPENDENT** | 新記憶と既存記憶は無関係 → 両方ともそのまま保存 |
| **EXTENDABLE** | 新記憶が既存記憶を拡張 → 既存記憶の metadata（tags, importance 等）を更新 |
| **CONTRADICTORY** | 新記憶が既存記憶と明確に矛盾 → 既存記憶を tombstone（論理削除）+ 新記憶を保存 |

### 実装

- `MemoryEnricher.classify_contradiction()`: LLM 1回呼出で分類
- `MemoryService._evolve_related_memories()`: semantic similarity check → 分類 → 処理
- 判定プロンプトは日本語。全処理 best-effort（LLM 障害時はスキップ）

### 既存の ContradictionDetector との関係

既存の `ContradictionDetector`（ベクトル類似度ベースの検出）は維持。LLM 分類は `_evolve_related_memories()` 内の進化パイプラインに統合され、より粒度の細かい処理を可能にします。

---

## Episode + Note 2-tier Memory (HiMem 着想)

[HiMem](https://arxiv.org/html/2601.06377) の核心: Episode Memory（生の会話ログ）と Note Memory（抽象化された知識）の2階層分離。HiMem の LoCoMo 80.71（Mem0 比 +12pt）は主に Episode Memory の寄与（除去で -11pt）。

### 階層構造

| 階層 | Nousでの位置付け | 内容 |
|---|---|---|
| **Episode Memory** | `session_events` テーブル | 生の会話ログ。Topic-Aware Event-Surprise Segmentation で分割 |
| **Note Memory** | `memories` テーブル | 抽出・抽象化された知識（facts, preferences, profile） |

### Episode Segmentation

`EpisodeSegmenter` が session events を topic shift + surprise scoring で自動分割:

- **Topic shift detection**: LLM が隣接する turn pair を比較し「トピックが変わったか？」を判定
- **Surprise signal**: 「この発言は予想外か？」を 0.0-1.0 で評価、閾値 > 0.7 で即時セグメンテーション
- **OR ルール**: topic shift OR surprise > 0.7 → セグメント境界
- **最小セグメント長**: 3 turns 未満は前セグメントにマージ（過剰分割防止）

### Consolidation Pipeline

`EpisodeConsolidation` が各 Episode から以下をLLM抽出 → `memories` に保存:

1. **K_fact**: 事実情報
2. **K_pref**: ユーザー好み
3. **K_profile**: プロフィール情報

### 2-tier Retrieval

`PrepareStep` の検索パイプライン:

1. Note Memory（`memories`）を最初に検索
2. 結果が `memory_preload_count` 未満の場合、Episode Memory（`session_events`）を fallback 検索
3. 見つかった episode reference を context に追加

### 設定

| 設定キー | デフォルト | 説明 |
|---|---|---|
| `episode_consolidation_enabled` | `True` | Episode → Note 統合の有効/無効 |
| `episode_search_enabled` | `True` | 2-tier fallback 検索の有効/無効 |

全処理 best-effort: セグメンテーション・統合・検索のいずれかが失敗してもメインの会話フローは継続。

---

## Agent Scheduled Tasks（schedule_task / agent:task）

エージェント（ペルソナ）が自分で決めた予定を登録し、指定時刻に自分で実行する機能（kanban #36/#64/#65）。builtin ツール `schedule_task` が `when`（ISO 日時か `+2h` 形式の相対表記、分精度）と `prompt` を、下記タグ付きの記憶として置く。`ProspectiveWorker`（`nous/application/workers/prospective_worker.py`）が期限に実行する。

| タグ | 役割 |
|---|---|
| `agent:task` | 予定そのもの（実行し終えたら外す） |
| `cue:time:<iso>` | 期限（分精度） |
| `cue:recur:daily\|weekly` | 繰り返し（実行後に次回の期限を入れ直す） |
| `agent:task:fail:<n>` | 失敗回数（Chat 設定 `tools.schedule_fail_limit`（既定3）で諦めて `agent.task.failed` を残す） |

### 実行の流れ

1. 期限になると worker が `run_self_turn` で `[自分で決めた予定] <prompt>` を 1 ターン走らせる（session_id=`self:<date>`）
2. 結果の発言は `speak_to_main` でユーザーの main チャットへ届く
3. 成功なら `agent:task` を外し、recur なら次回の `cue:time` を入れ直す。失敗なら失敗回数を足して次の巡回で再挑戦

### 精度とグレース（kanban #68）

- **定時実行**: worker は最短の未来期限まで眠るので、期限の `workers.prospective_min_wait_seconds`（既定 30 秒）以降に走る。未来の期限が1つもない時だけ `workers.prospective_interval_seconds`（既定 3600 秒）で周期的に起きる（どちらもループ毎に設定を読み直す）
- **譲り渡し**: 期限時に他のターン（ユーザーとの会話など）が走っていると実行を譲り、タグを外さず次の巡回（最大 1 時間後）で拾い直す
- **過期グレース**: 期限を過ぎたタスクも `72h`（`OVERDUE_GRACE_HOURS`）以内なら対象。それより古いものは拾わない
- **巡回対象**: 起動後に一度でも HTTP/チャットでアクセスされたペルソナだけ。触られていないペルソナの期限は拾われない
