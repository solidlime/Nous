# Memory Features

This document describes the advanced memory management features.

---

## FSRS v6 Power-Law Forgetting Curve

Memories decay over time according to the [FSRS v6 power-law forgetting curve](https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm), validated against real human recall data via Anki benchmarks:

```
R(t) = (1 + 19 · t / S)^(-0.5)
```

| Variable | Description |
|----------|-------------|
| `R` | Retention (0.0–1.0) |
| `t` | Days since last access (in hours internally) |
| `S` | Stability in days (grows on each recall) |
| `decay_exponent` | 0.5 (canonical FSRS v6) |

**Effective search score**: `strength = importance × R(t)`

> **Why power-law?** FSRS starts with faster initial decay than Ebbinghaus but maintains a much heavier tail — memories survive far longer in the "barely remembered" zone. This better models human long-term memory.

### How it works

1. When a memory is created, its initial stability is set based on emotional charge:
   - `emotion_intensity > 0.7` → S = 10 (emotionally vivid, hard to forget)
   - `emotion_intensity > 0.5` → S = 5
   - otherwise → S = 1

2. Every 6 hours, a background worker recomputes `strength` for all memories.

3. When a memory is recalled (returned by search), its stability is multiplied by 1.5 (capped at 365 days), effectively resetting the decay clock. This models the "spacing effect."

4. Search ranking uses `strength` instead of raw `importance` when `importance_weight > 0`.

### Key columns

| Table | Column | Description |
|-------|--------|-------------|
| `memories` | `importance` | Immutable score set at creation |
| `memory_strength` | `strength` | Current effective score (decayed) |
| `memory_strength` | `stability` | Current stability factor |
| `memory_strength` | `last_decay_at` | Last time the decay worker ran |

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

## Named Memory Blocks

Inspired by [Letta (MemGPT)](https://letta.com/), memory blocks are structured segments that are **always included in `get_context()` output** — unlike regular memories which require a search query.

Think of them as "RAM" for the AI: a small set of key facts always in working memory.

### Standard block names

| Name | Purpose |
|------|---------|
| `persona_state` | The persona's current internal state, mood, ongoing goals |
| `user_model` | What the persona knows/infers about the user |
| `active_context` | Current session focus, open questions, ongoing topics |

Custom block names are also allowed.

### Operations via `memory()` tool

```python
# Write a block
memory(operation="block_write", block_name="user_model",
        content="らうらうはNousを開発中。Python好き。")

# Read a specific block
memory(operation="block_read", block_name="user_model")

# List all block names
memory(operation="block_list")

# Delete a block
memory(operation="block_delete", block_name="user_model")
```

### Schema

```sql
CREATE TABLE memory_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    persona     TEXT NOT NULL,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    description TEXT DEFAULT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(persona, name)
);
```

### HTTP API でのアクセス

Block memory は MCP ツール経由に加え、HTTP API 経由でも操作できる。

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/api/blocks/{persona}` | ブロック一覧を取得 |
| `POST` | `/api/blocks/{persona}` | ブロックを書き込み（`block_name` + `content` 必須） |
| `DELETE` | `/api/blocks/{persona}/{block_name}` | ブロックを削除 |

詳細は [HTTP API Reference — Core Memory Blocks](./http_api_reference.md#core-memory-blocks) を参照。

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

## LLM Summary Compaction (Stage 4)

`CompressStep` の第4段階として、機械的圧縮（行数トリム・古いツール結果クリア・メッセージ切り詰め）だけではコンテキストが予算超過している場合に、LLM を使って古い会話を要約します。

### 動作

1. **トリガー条件**: 以下のすべてを満たす場合のみ実行
   - `context_use_llm_summary = True`（デフォルト: `True`）
   - APIキーが設定されている
   - 会話ターン数が6以上（十分な履歴がある場合のみ価値がある）
   - Stage 1-3 の機械圧縮後もコンテキストが予算超過
2. 最も古いターン（直近の `keep_recent` ターンを除く全メッセージ）を抽出
3. LLM に要約プロンプト（日本語）を送信し、**300文字以内**の要約を生成
4. 古いメッセージを要約メッセージ `[過去の会話要約] ...` に置き換え

### 設定

| 設定キー | デフォルト | 説明 |
|---|---|---|
| `context_use_llm_summary` | `True` | Stage 4 の有効/無効 |

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
