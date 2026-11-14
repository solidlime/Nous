# Nous v3.x 記憶システム人間化改革 実装計画

> **For agentic workers:** 各チャンクは独立して実装可能。Steps は checkbox (`- [ ]`) 構文で追跡すること。TDD厳守（RED→GREEN→REFACTOR）。コミットは頻繁に。1タスク = 1PR = 全テストパス厳守。

**Goal:** Nous の記憶システムに「人間らしさ」を導入——構造（memory kind, links, source provenance）、想起（emotion modulation, spreading activation, reflection）、注釈（language-agnostic recall annotations for LLM-driven expression）の3層改革。

**Architecture:** 記憶を単なるベクトル検索＋FSRS減衰から、認知科学的に妥当な「エピソード/意味記憶の分離」「Hebbian連想ネットワーク」「自己編集ループ」「文脈依存想起」を持つシステムへ進化させる。表現層は**文章生成ではなくメタデータ注釈付与**に徹し、LLMが各自のペルソナ口調で自然な想起表現を生成する。全モジュールは言語・ペルソナ非依存。

**Tech Stack:** Python 3.12+, SQLite, Qdrant (AsyncQdrantClient), FSRS v6, Sudachi (NER), FastAPI

**依存関係:**
```
Chunk 0（Qdrant async化）── 全チャンクの前提。最優先で単独完了させる。
         │
Chunk 1（構造基盤）──┬── Chunk 3（想起エンジン）── Chunk 4（想起注釈層）
         │
Chunk 2（ドキュメント）── 独立（いつでも並行可）
```

---

## Chunk 0: 前提インフラ整備（最優先・単独）

### Task 0: Qdrant async client 移行

**背景:** `adapter.py` が同期 `QdrantClient` を async 関数内で直接呼び出しており、イベントループをブロックしている。Chunk 1 の memory_links 生成（類似候補検索が Qdrant 依存）を sync のまま実装すると `create_memory()` が数秒ブロックするため、全チャンクの前提として最優先で完了させる。

**重要:** このタスクだけで 1 チャンク分の作業量がある。adapter.py の全 14 メソッド（sync 8 + async 6）を単一の async インターフェースに統一し、呼び出し元も全修正する。完了後は sync 版メソッドを削除して二重メンテナンスを避ける。

**Files:**
- Modify: `nous/infrastructure/qdrant/client.py` — `AsyncQdrantClient` 導入
- Modify: `nous/infrastructure/qdrant/adapter.py` — 全メソッド async 化、sync 版削除
- Modify: `nous/domain/search/engine.py` — adapter 呼び出しを await
- Modify: `nous/domain/memory/service.py` — adapter 呼び出しを await
- Modify: 全テストで adapter を使っている箇所 — `@pytest.mark.asyncio` 追加
- Test: `tests/unit/test_qdrant_adapter_async.py` (新規)

- [ ] **Step 1: QdrantClientManager を AsyncQdrantClient ベースに**

```python
# nous/infrastructure/qdrant/client.py
from qdrant_client import AsyncQdrantClient

class QdrantClientManager:
    def __init__(self, url: str = "http://localhost:6333", api_key: str | None = None):
        self._url = url
        self._api_key = api_key
        self._client: AsyncQdrantClient | None = None
        self._lock = asyncio.Lock()

    @property
    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            raise RuntimeError("Client not connected. Call async connect() first.")
        return self._client

    async def connect(self) -> AsyncQdrantClient:
        async with self._lock:
            if self._client is None:
                self._client = AsyncQdrantClient(
                    url=self._url,
                    api_key=self._api_key,
                    timeout=30.0,
                )
            return self._client

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
```

- [ ] **Step 2: adapter.py の全メソッドを async に統一**

```python
# adapter.py — すべてのメソッドを async def にし、sync 版は削除
class QdrantVectorStore:
    async def ensure_collection(self, persona: str, vector_size: int) -> Result:
        ...
    
    async def upsert(self, persona: str, memory: Memory, embedding: list[float]) -> Result:
        ...
    
    async def search(self, persona: str, query_vector: list[float], limit: int) -> Result:
        response = await self.client_manager.client.query_points(
            collection_name=self.collection_name(persona),
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        ...
    
    # 以下同様に全メソッド async 化
    # sync 版の ensure_collection_sync, upsert_sync, search_sync 等は削除
```

- [ ] **Step 3: 全呼び出し元の await 化**

`nous/domain/search/engine.py`:
```python
# 修正前
result = self._vector_store.search(persona, embedding, limit)
# 修正後
result = await self._vector_store.search(persona, embedding, limit)
```

`nous/domain/memory/service.py`: 同様に全 `await` 追加。

- [ ] **Step 4: テストを asyncio 対応に**

```python
# tests/unit/test_qdrant_adapter_async.py
@pytest.mark.asyncio
async def test_async_upsert_and_search(mock_qdrant_client):
    store = QdrantVectorStore(client_manager=mock_manager)
    result = await store.upsert("test_persona", mock_memory, [0.1] * 768)
    assert result.is_ok()
```

既存テストの adapter 呼び出し箇所にも `@pytest.mark.asyncio` と `await` を追加。

- [ ] **Step 5: テスト実行 + コミット**

```bash
pytest tests/unit/test_qdrant_adapter_async.py tests/unit/test_search_engine.py -v
```

```bash
git commit -m "refactor: migrate Qdrant to AsyncQdrantClient (Chunk 0 — unblocks memory reform)"
```

---

## Chunk 1: 記憶の構造改革（Memory Structure Layer）

### Task 1.1: memories.kind カラム追加

**背景:** Tulving 1972 の episodic/semantic 二分法を導入。既存 memory は全て `kind='semantic'` にマイグレーション。**重要: SQLite は `ALTER TABLE ADD COLUMN` に `CHECK` 制約をサポートしない。バリデーションはアプリケーション層（Memory エンティティの `__post_init__`）で行う。**

**Files:**
- Create: `nous/migration/versions/v033_memory_kind.py`
- Modify: `nous/domain/memory/entities.py` — Memory dataclass に kind 追加 + `__post_init__` バリデーション
- Modify: `nous/domain/memory/value_objects.py`
- Modify: `nous/infrastructure/sqlite/memory_repo.py` — `_row_to_memory()`, `insert_memory()`
- Modify: `nous/domain/memory/service.py` — `create_memory()` に kind パラメータ追加
- Modify: `nous/api/mcp/_tools_memory.py` — `memory_create()` のツール定義に kind 追加
- Test: `tests/unit/test_memory_kind.py` (新規)
- Test: `tests/integration/test_memory_service.py` (既存、kind 付きテスト追加)

- [ ] **Step 1: マイグレーション（実際のエンジン形式に合わせる）**

```python
# nous/migration/versions/v033_memory_kind.py
"""v033: Add kind column for episodic/semantic/procedural/prospective memory types."""

def upgrade(db) -> None:
    db.execute("ALTER TABLE memories ADD COLUMN kind TEXT NOT NULL DEFAULT 'semantic'")
    db.execute("ALTER TABLE memories ADD COLUMN episodic_time TEXT")
    db.execute("ALTER TABLE memories ADD COLUMN episodic_place TEXT")
    db.execute("ALTER TABLE memories ADD COLUMN episodic_people TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")
    db.commit()
```

- [ ] **Step 2: Memory エンティティに kind バリデーション追加**

```python
# nous/domain/memory/entities.py
VALID_KINDS = frozenset(["episodic", "semantic", "procedural", "prospective"])

@dataclass
class Memory:
    # ... 既存フィールド ...
    kind: str = "semantic"
    episodic_time: str | None = None
    episodic_place: str | None = None
    episodic_people: str | None = None  # JSON array

    def __post_init__(self):
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Invalid kind: {self.kind}. Must be one of {VALID_KINDS}")
        # ... 既存のバリデーション ...
```

- [ ] **Step 3: memory_repo + memory_service 更新**

`nous/infrastructure/sqlite/memory_repo.py:_row_to_memory()`:
```python
kind = row["kind"] if "kind" in row.keys() else "semantic"
```

`nous/domain/memory/service.py:create_memory()`:
```python
async def create_memory(
    self, persona: str, content: str,
    kind: str = "semantic",
    importance: float | None = None, ...
) -> Result[Memory]:
```

- [ ] **Step 4: MCP ツールの kind パラメータ追加**

`nous/api/mcp/_tools_memory.py:memory_create()`:
```python
# kind パラメータをツール定義に追加（任意、デフォルト "semantic"）
# オプションで LLM による自動分類プロンプトを追加（後続タスクで実装）
```

- [ ] **Step 5: テスト実行**

```bash
pytest tests/unit/test_memory_kind.py tests/integration/test_memory_service.py -v
```

- [ ] **Step 6: コミット**

```bash
git commit -m "feat: add memory kind column (episodic/semantic/procedural/prospective)"
```

---

### Task 1.2: valence カラム + Bower 気分一致想起 bias

**背景:** SPEC R04c（感情持続性）を拡張し、Bower 1981 の気分一致想起を実装。現在の `boost_on_recall(emotion_intensity=0.0)` が常に 0 で呼ばれているバグも同時修正。**YAGNI: flashbulb_marker と suppressed は今回スコープ外。valence のみ追加する。**

**Files:**
- Create: `nous/migration/versions/v034_valence.py`
- Modify: `nous/domain/memory/entities.py` — MemoryStrength に valence 追加
- Modify: `nous/domain/memory/service.py` — `boost_recall()` の emotion_intensity 伝搬バグ修正
- Modify: `nous/domain/search/ranker.py` — `EmotionRecallBiasRanker` 追加
- Modify: `nous/domain/search/engine.py` — ランカーチェーンに追加
- Test: `tests/unit/test_emotion_recall_bias.py` (新規)

- [ ] **Step 1: マイグレーション**

```python
# nous/migration/versions/v034_valence.py
def upgrade(db) -> None:
    db.execute("ALTER TABLE memory_strength ADD COLUMN valence REAL DEFAULT 0.0")
    db.commit()
```

- [ ] **Step 2: boost_recall の emotion_intensity 伝搬修正**

`nous/domain/memory/service.py`:
```python
# 修正前
strength.boost_on_recall()  # emotion_intensity 常に 0.0

# 修正後: 呼び出し元の PersonaState から emotion_intensity を取得して渡す
strength.boost_on_recall(emotion_intensity=persona_state.emotion_intensity)
```

- [ ] **Step 3: EmotionRecallBiasRanker 実装**

```python
# nous/domain/search/ranker.py
class EmotionRecallBiasRanker(BaseRanker):
    """Bower 1981: 現在の気分と一致する感情価の記憶をブースト"""
    
    def rank(self, results, persona_state=None):
        if persona_state is None:
            return results
        mood_valence = getattr(persona_state, 'valence', 0.0)
        if mood_valence == 0.0:
            return results  # ニュートラル気分ではバイアスなし
        
        for r in results:
            memory_valence = r.metadata.get("valence", 0.0)
            valence_match = 1.0 - abs(memory_valence - mood_valence) / 2.0
            r.score *= (1.0 + 0.2 * valence_match)
        return results
```

- [ ] **Step 4: テスト**

```python
def test_positive_mood_boosts_positive_memories():
    ...

def test_neutral_mood_no_bias():
    ...

def test_negative_mood_boosts_negative_memories():
    ...
```

- [ ] **Step 5: コミット**

```bash
git commit -m "feat: add valence + Bower 1981 emotion-congruent recall bias"
```

---

### Task 1.3: memory_links 正規化テーブル + Hebbian 共活性化

**背景:** 既存 `related_keys` を正規化し、Collins & Loftus 1975 の拡散活性化理論 + Hebbian co-activation 原則に基づく重み付き連想ネットワークを構築。**重要: リンクは「同時にアクセスされた記憶同士」にのみ生成する（Hebbian の co-fire 原則）。類似度だけでのリンク生成は禁止。閾値: cosine similarity ≥ 0.8 かつ 同一会話ターン内でのアクセス。また、create_memory() 内の 3 テーブル同時書き込みにトランザクション境界を導入する。**

**Files:**
- Create: `nous/migration/versions/v035_memory_links.py`
- Create: `nous/domain/memory/memory_link.py` — MemoryLink ドメインオブジェクト
- Create: `nous/infrastructure/sqlite/memory_link_repo.py` — MemoryLinkRepository
- Modify: `nous/infrastructure/sqlite/connection.py` — AsyncTransactionContext 追加
- Modify: `nous/domain/memory/service.py` — `create_memory()` のトランザクション化 + 共活性リンク生成
- Test: `tests/unit/test_memory_links.py` (新規)
- Test: `tests/integration/test_memory_link_integration.py` (新規)

- [ ] **Step 0: トランザクションラッパーを実装（Step 1-2 より前に最重要）**

```python
# nous/infrastructure/sqlite/connection.py
from contextlib import asynccontextmanager

class DatabaseManager:
    """既存の get_memory_db() / get_log_db() に transaction() を追加"""
    
    @asynccontextmanager
    async def transaction(self):
        """sqlite3 の同期トランザクションを asyncio.to_thread でラップ"""
        def _tx():
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        # 注: sqlite3 の同期操作を asyncio.to_thread で実行することで
        # イベントループをブロックせずトランザクションを実現する
        # 2026-07 MCP spec 更新時に AsyncSQLite に移行するまでの暫定措置
        await asyncio.to_thread(lambda: self._conn.execute("BEGIN IMMEDIATE"))
        try:
            yield
            await asyncio.to_thread(self._conn.commit)
        except Exception:
            await asyncio.to_thread(self._conn.rollback)
            raise
```

- [ ] **Step 1: マイグレーション**

```python
# nous/migration/versions/v035_memory_links.py
def upgrade(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_links (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5,
            link_type TEXT NOT NULL DEFAULT 'semantic',
            co_activation_count INTEGER DEFAULT 0,
            last_activated TEXT,
            PRIMARY KEY (source_key, target_key, link_type)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_key)")
    db.commit()
```

- [ ] **Step 2: MemoryLink ドメインオブジェクト**

```python
# nous/domain/memory/memory_link.py
from dataclasses import dataclass

LINK_TYPES = frozenset(["semantic", "temporal", "emotional", "contextual", "causal"])

@dataclass
class MemoryLink:
    source_key: str
    target_key: str
    weight: float = 0.5
    link_type: str = "semantic"
    co_activation_count: int = 0
    last_activated: str | None = None

    def hebbian_update(self, co_activation_strength: float = 0.1):
        """Hebbian: co-fire で重み強化。上限 1.0"""
        self.weight = min(1.0, self.weight + co_activation_strength)
        self.co_activation_count += 1
        self.last_activated = datetime.now(timezone.utc).isoformat()

    def decay(self, rate: float = 0.01):
        """未使用リンクの減衰。下限 0.1"""
        self.weight = max(0.1, self.weight - rate)
```

- [ ] **Step 3: create_memory のトランザクション化 + Hebbian リンク生成**

```python
# nous/domain/memory/service.py
async def create_memory(self, persona: str, content: str, **kwargs) -> Result[Memory]:
    memory = Memory(persona=persona, content=content, ...)
    
    # トランザクション開始
    async with self._db.transaction():
        # 1. メモリ本体を保存
        saved = await self._memory_repo.insert(memory)
        
        # 2. MemoryStrength を保存
        await self._strength_repo.insert(saved.key, MemoryStrength())
        
        # 3. Hebbian co-activation links を生成
        # 同一会話ターン内の最近アクセスされた記憶とのみリンク
        co_accessed = await self._find_co_accessed(persona, saved)
        for candidate in co_accessed:
            if self._meets_link_threshold(saved, candidate):
                link_type = self._classify_link_type(saved, candidate)
                await self._link_repo.upsert(saved.key, candidate.key, link_type)
    
    return Result.ok(saved)

def _meets_link_threshold(self, m1: Memory, m2: Memory) -> bool:
    """Hebbian co-fire: 同時アクセス + cosine ≥ 0.8"""
    similarity = cosine_similarity(m1.embedding, m2.embedding)
    return similarity >= 0.8

async def _find_co_accessed(self, persona: str, new_memory: Memory) -> list[Memory]:
    """同一会話ターン内でアクセスされた記憶を取得"""
    # session_event テーブルから現在の会話セッションのアクセスログを検索
    ...
```

- [ ] **Step 4: テスト**

```python
# 単体テスト
def test_hebbian_weight_update():
    link = MemoryLink("a", "b")
    link.hebbian_update(0.1)
    assert link.weight == 0.6
    assert link.co_activation_count == 1

def test_hebbian_weight_capped_at_one():
    link = MemoryLink("a", "b", weight=0.95)
    link.hebbian_update(0.1)
    assert link.weight == 1.0

# 統合テスト
@pytest.mark.asyncio
async def test_link_creation_on_co_accessed_memory():
    ...

@pytest.mark.asyncio
async def test_no_link_when_similarity_below_threshold():
    ...
```

- [ ] **Step 5: コミット**

```bash
git commit -m "feat: memory_links table + Hebbian co-activation network (co-fire threshold ≥0.8)"
```

---

### Task 1.4: source_type + confidence カラム追加

**背景:** Johnson 1993 Source Monitoring + Bartlett 1932 Schema Reconstruction。LLM推論由来の記憶に確信度を付与し、事実と推測を区別する。**コストを抑えるため、LLM による自動分類は最小限に留め、deterministic ルールを優先。**

**Files:**
- Create: `nous/migration/versions/v036_source_provenance.py`
- Modify: `nous/domain/memory/entities.py` — Memory に source_type, confidence 追加
- Modify: `nous/infrastructure/sqlite/memory_repo.py`
- Test: `tests/unit/test_source_provenance.py` (新規)

- [ ] **Step 1: マイグレーション**

```python
# nous/migration/versions/v036_source_provenance.py
def upgrade(db) -> None:
    db.execute("ALTER TABLE memories ADD COLUMN source_type TEXT NOT NULL DEFAULT 'user_stated'")
    db.execute("ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0")
    db.execute("ALTER TABLE memories ADD COLUMN derived_from TEXT")
    db.commit()
```

- [ ] **Step 2: ソースタイプ分類ルール（deterministic 優先）**

```python
# memories の source_type 割り当てルール:
# - MCP memory_create() から直接呼ばれた場合 → 'user_stated'
# - run_memory_llm() の fact 抽出 → 'llm_inferred'
# - Reflection の insight → 'reflected'
# - Consolidation の要約 → 'consolidated'
# - 外部ツール出力 → 'tool_output'

# confidence の計算:
# - user_stated: 1.0
# - llm_inferred: 0.7
# - reflected: 0.7 (insight は推論なので確信度は下げる)
# - consolidated: 0.6
```

- [ ] **Step 3: テスト + コミット**

```bash
git commit -m "feat: source_type + confidence columns for Bartlett source monitoring"
```

---

## Chunk 2: ドキュメント整備（Documentation & CI）

**※ 独立チャンク。Chunk 0,1 と並行して進めてよい。**

### Task 2.1: CLAUDE.md を v3 フラットツール API に更新

**Files:** `CLAUDE.md:63-73`

- [ ] **Step 1: ツール一覧をフラット形式に書き換え**

```markdown
## MCP ツール (v3)
- `memory_create(content, importance?, tags?, kind?, ...)` — 新規記憶
- `memory_read(memory_key?, limit?, offset?)` — 記憶の読み取り
- `memory_update(memory_key, ...)` — 更新（バージョン管理付き）
- `memory_delete(memory_key | query)` — 論理削除 (tombstone)
- `memory_search(query, top_k?, vector_weight?, keyword_weight?)` — ハイブリッド検索
- `memory_stats()` — 統計
- `update_context(emotion?, body_state?, ...)` — ペルソナ状態更新
- `get_context()` — ペルソナ状態取得
- `item(operation, ...)` — 装備品管理
- `goal_manage(operation, ...)` — 目標管理
```

- [ ] **Step 2: コミット**

```bash
git commit -m "docs: update CLAUDE.md to v3 flat tool API"
```

---

### Task 2.2: ドキュメント修正（バージョン不一致・アーキテクチャ不整合）

**Files:**
- `docs/http_api_reference.md:52` — version "2.0.0" → "3.0.0"
- `docs/sandbox.md` — DinD → DooD 構成に全面改訂
- `.agent/memory/MEMORY.md:117` — httpx Timeout 記述訂正
- `GEMINI.md` — 最低限の AI ガイダンス追加（CLAUDE.md 参照指示 + 差分のみ）
- `requirements.txt` — bandit/mypy/playwright 等の開発依存を `[dev]` optional-dependencies に分離

- [ ] **Step 1: 各ファイル修正 + コミット**

```bash
git commit -m "docs: fix version/architecture inconsistencies in docs"
```

---

### Task 2.3: CI ハードニング + Docker 非root化

**Files:**
- `.github/workflows/ci.yml` — mypy/bandit をブロッキングに
- `Dockerfile` — 非rootユーザー追加
- `pyproject.toml` — `[project.optional-dependencies] dev` にテスト依存分離

- [ ] **Step 1: CI 修正**

```yaml
# mypy と bandit の continue-on-error を削除
```

- [ ] **Step 2: コミット**

```bash
git commit -m "ci: make mypy/bandit blocking; Docker non-root user"
```

---

## Chunk 3: 想起エンジン改革（Retrieval Layer）

### Task 3.1: Qdrant 固定 exp_decay 除去 → FSRS に統一

**背景:** `adapter.py:_build_decay_query()` の固定 `decay_scale=604800` が `ForgettingCurveRanker` の FSRS 動的 stability と競合（二重減衰問題）。Qdrant 側の exp_decay を除去し、`ForgettingCurveRanker` が減衰の唯一の担い手となる。

**Files:**
- Modify: `nous/infrastructure/qdrant/adapter.py:_build_decay_query()`
- Modify: `nous/domain/search/ranker.py:ForgettingCurveRanker`
- Test: `tests/unit/test_search_engine.py` (既存テストの更新)

- [ ] **Step 1: Qdrant 側の exp_decay 削除**

```python
# adapter.py - _build_decay_query から decay パラメータを完全に除去
def _build_query_request(self, embedding, limit):
    return {
        "vector": embedding,
        "limit": limit,
        "with_payload": True,
        # decay=DecayParamsExpression(...)  ← 削除
    }
```

- [ ] **Step 2: ForgettingCurveRanker に FSRS recall probability を統合**

```python
# ranker.py
class ForgettingCurveRanker:
    def rank(self, results):
        for r in results:
            strength = self._get_strength(r.memory_key)
            if strength:
                elapsed = (utcnow() - r.created_at).total_seconds()
                stability = strength.stability  # 動的 (FSRS v6)
                recall = (1 + 19 * elapsed / (stability * 86400)) ** -0.5
                r.score *= (0.3 + 0.7 * recall)  # 0.3: 最低保証
        return results
```

- [ ] **Step 3: テスト — 二重減衰がないことの検証**

```python
def test_no_double_decay():
    """Qdrant 減衰削除後、ForgettingCurveRanker のみが減衰を適用すること"""
    ...

def test_forgetting_curve_stability_affects_ranking():
    """stability が高い記憶ほど検索スコアが高く保たれること"""
    ...
```

- [ ] **Step 4: コミット**

---

### Task 3.2: Spreading Activation 検索統合

**背景:** Chunk 1.3 で作成した memory_links の重み付きエッジを使って、シード記憶から 2-hop の連想活性化を伝播させる。Collins & Loftus 1975 + SYNAPSE 2026。

**Files:**
- Create: `nous/domain/search/spreading_activation.py`
- Modify: `nous/domain/search/engine.py` — `_hybrid_search()` に SA 統合
- Test: `tests/unit/test_spreading_activation.py` (新規)

- [ ] **Step 1: SpreadingActivation エンジン実装**

```python
# nous/domain/search/spreading_activation.py
@dataclass
class SpreadingActivation:
    hops: int = 2
    decay: float = 0.5
    retention: float = 0.3
    threshold: float = 0.01

    def propagate(self, seed_keys: list[str], links: list[MemoryLink]) -> dict[str, float]:
        activation = {k: 1.0 for k in seed_keys}
        for _ in range(self.hops):
            next_act: dict[str, float] = {}
            for src, curr in activation.items():
                if curr <= self.threshold:
                    continue
                outgoing = [l for l in links if l.source_key == src]
                degree = max(len(outgoing), 1)
                for link in outgoing:
                    spread = (curr * (1 - self.retention) * link.weight) / degree
                    next_act[link.target_key] = next_act.get(link.target_key, 0) + spread
                next_act[src] = next_act.get(src, 0) + curr * self.retention
            for k in set(activation) | set(next_act):
                activation[k] = activation.get(k, 0) * self.decay + next_act.get(k, 0)
        return {k: v for k, v in activation.items() if k not in seed_keys}
```

- [ ] **Step 2: SearchEngine に統合**

```python
# engine.py: _hybrid_search()
async def _hybrid_search(self, query, persona, limit=10):
    base_results = await self._base_search(query, persona, limit=20)
    
    if self._link_repo and base_results:
        seed_keys = [r.memory_key for r in base_results[:5]]
        all_links = await self._link_repo.get_links_for_keys(seed_keys)
        sa = SpreadingActivation()
        activations = sa.propagate(seed_keys, all_links)
        for r in base_results:
            if r.memory_key in activations:
                r.score += activations[r.memory_key] * 0.2  # SA 重み 0.2
    
    return sorted(base_results, key=lambda r: r.score, reverse=True)[:limit]
```

- [ ] **Step 3: テスト**

```python
def test_spreading_activation_two_hop_decay():
    links = [
        MemoryLink("a", "b", weight=0.8),
        MemoryLink("b", "c", weight=0.6),
    ]
    sa = SpreadingActivation(hops=2, decay=0.5, retention=0.3)
    result = sa.propagate(["a"], links)
    assert result["b"] > result["c"]  # 1-hop > 2-hop

def test_below_threshold_ignored():
    ...
```

- [ ] **Step 4: コミット**

---

### Task 3.3: Reflection Pipeline（自己編集ループ）

**背景:** Generative Agents (Park 2023) の reflection ループ。現在の MemoryLLM は原子的 fact 抽出のみで、高次洞察がない。LLM に「直近 N 件の記憶からパターン・傾向を導出」させ、insight を source_type='reflected' で再保存する。

**重要: Chunk 4 の設計原理「注釈はメタデータ、表現は LLM」を Reflection にも適用する。**
プロンプトは言語非依存の構造化データとして定義し、LLM が自身の言語で解釈する。

**Files:**
- Create: `nous/application/chat/reflection.py`
- Create: `nous/domain/memory/reflection_schema.py` — 言語非依存の reflection 指示スキーマ
- Modify: `nous/application/chat/memory_llm.py` — reflection トリガー追加
- Modify: `nous/application/workers/decay_worker.py` — 定期 reflection 組み込み
- Test: `tests/unit/test_reflection_pipeline.py` (新規)

- [ ] **Step 1: 言語非依存 ReflectionSchema の定義**

```python
# nous/domain/memory/reflection_schema.py
@dataclass(frozen=True)
class ReflectionQuestion:
    id: str
    intent: str  # 言語非依存の意図キー
    output_key: str

REFLECTION_SCHEMA = [
    ReflectionQuestion(
        id="patterns",
        intent="identify patterns, trends, or recurring themes across recent episodic memories",
        output_key="insight",
    ),
    ReflectionQuestion(
        id="user_traits",
        intent="identify stable user traits, preferences, or notable changes",
        output_key="insight",
    ),
    ReflectionQuestion(
        id="implications",
        intent="derive implications or predictions for future conversations",
        output_key="insight",
    ),
]

OUTPUT_FORMAT = {
    "type": "json_array",
    "items": {
        "insight": "string (the synthesized insight)",
        "evidence_keys": "array of memory keys that support this insight",
        "confidence": "float 0.0-1.0",
    },
}
```

- [ ] **Step 2: ReflectionEngine 実装（言語非依存）**

```python
# nous/application/chat/reflection.py
class ReflectionEngine:
    """Park et al. 2023: question → search → synthesize → reinsert.
    Language-agnostic: uses structured schema, not hardcoded prompts."""
    
    def __init__(self, reflection_schema: list[ReflectionQuestion] = REFLECTION_SCHEMA):
        self._schema = reflection_schema

    async def reflect(self, persona: str, memory_service, llm) -> list[Memory]:
        recent = await memory_service.get_recent(persona, limit=50, kind="episodic")
        
        # LLM はシステムプロンプトに従い、自身の言語で質問を解釈し回答する
        # プロンプトテンプレートはデフォルト英語、config で上書き可能
        system_msg = self._build_system_message(persona, recent)
        insights = await llm.generate_structured(system_msg, OUTPUT_FORMAT)
        
        new_memories = []
        for insight in insights:
            mem = await memory_service.create_memory(
                persona=persona,
                content=insight["insight"],
                kind="semantic",
                source_type="reflected",
                confidence=insight.get("confidence", 0.7),
                importance=0.8,
                tags=["reflection"],
                derived_from=insight.get("evidence_keys", []),
            )
            new_memories.append(mem)
        return new_memories

    def _build_system_message(self, persona: str, memories: list) -> str:
        """Generate language-agnostic system message.
        Default: English. Override via REFLECTION_SYSTEM_PROMPT in chat_config."""
        import json
        schema_desc = json.dumps([{"id": q.id, "intent": q.intent, "output": q.output_key}
                                  for q in self._schema])
        return f"""You are {persona}. Analyze recent memories and generate insights.

Reflection tasks:
{schema_desc}

Output format: {json.dumps(OUTPUT_FORMAT)}

Recent memories:
{chr(10).join(f"- {m.content}" for m in memories)}

Generate insights in your persona's natural language."""
```

- [ ] **Step 3: DecayWorker に定期 reflection 統合**

```python
# decay_worker.py
REFLECTION_INTERVAL = 50  # 記憶が50件増えるごとに reflection 実行

async def _run_cycle(self, persona):
    await self._process_decay(persona)
    if await self._should_reflect(persona):
        await self._reflection_engine.reflect(persona, ...)
```

- [ ] **Step 4: テスト + コミット**

---

### Task 3.4: Entity extraction 軽量 NER 化（Sudachi）

**背景:** 現状の regex-only 2-type 抽出を Sudachi（軽量、約 70MB）で 3+ type に拡張。**ja_ginza (1GB) は重すぎるため不採用。高速パスは既存 regex を維持し、Sudachi は非同期バックグラウンドで実行。**

**Files:**
- Create: `nous/domain/memory/sudachi_extractor.py`
- Modify: `nous/domain/memory/entity_extractor.py` — HybridEntityExtractor
- Modify: `pyproject.toml` — `sudachipy>=0.6.0` 依存追加
- Test: `tests/unit/test_sudachi_extractor.py` (新規, `@pytest.mark.slow`)

- [ ] **Step 1: Sudachi 依存追加**

```toml
# pyproject.toml
dependencies = [
    "sudachipy>=0.6.0",
    "sudachidict_core>=20240716",
]
```

- [ ] **Step 2: HybridEntityExtractor 実装**

```python
# nous/domain/memory/entity_extractor.py
class HybridEntityExtractor:
    """高速: regex (既存) / 高精度: Sudachi NER (非同期)"""
    
    def __init__(self):
        self._fast = SimpleEntityExtractor()  # 既存 regex
        self._sudachi: SudachiExtractor | None = None
    
    def extract_fast(self, text: str) -> list[Entity]:
        """会話中の低レイテンシ抽出"""
        return self._fast.extract(text)
    
    async def extract_accurate(self, text: str) -> list[Entity]:
        """バックグラウンド NER、Sudachi 遅延ロード"""
        if self._sudachi is None:
            self._sudachi = SudachiExtractor()
        return await asyncio.to_thread(self._sudachi.extract, text)
```

- [ ] **Step 3: テスト（slow マーカー付き）**

```python
@pytest.mark.slow
def test_sudachi_extracts_person_and_location():
    extractor = SudachiExtractor()
    entities = extractor.extract("田中さんが東京で会議に参加した")
    assert any(e.type == "person" for e in entities)
    assert any(e.type == "location" for e in entities)
```

- [ ] **Step 4: コミット**

```bash
git commit -m "feat: hybrid entity extraction (regex fast-path + Sudachi NER slow-path)"
```

---

## Chunk 4: 想起注釈層 — ペルソナ・言語非依存のメタデータ付与（Recall Annotation Layer）

**設計原理:** LLM はシステムプロンプトを通じてペルソナの話し方・口調を既に知っている。表現層の役割は「文章を生成すること」ではなく「記憶に注釈（hint）をつけること」。LLM が注釈を見て自分で自然な言い回しを選ぶ。英語・日本語・その他言語すべてで、どのペルソナでも破綻しない。

**データフロー:**
```
SearchEngine → [memory + recall_score]
     ↓
RecallAnnotator → [memory + annotation]   ← ここが Chunk 4
     ↓
PrepareStep → [context with annotated memories]
     ↓
LLM (システムプロンプトで persona 口調を知っている) → 自然な想起表現
```

**生成する注釈（RecallAnnotation）:**
| フィールド | 型 | 算出元 | 意味 |
|---|---|---|---|
| `certainty` | `"confident" \| "tentative" \| "vague" \| "forgotten"` | confidence + age_days | 確信度ヒント |
| `time_hint` | `"recent" \| "days_7" \| "days_30" \| "days_90" \| "years"` | age_days | 時間距離ヒント |
| `source_hint` | `"user_stated" \| "llm_inferred" \| "reflected" \| "consolidated"` | source_type | 情報源ヒント |
| `kind_hint` | `"episodic" \| "semantic" \| "procedural" \| "prospective"` | kind | 記憶種別ヒント |
| `should_mention` | `bool` | certainty != "forgotten" | 発話すべきか |

**LLM への指示（システムプロンプトに追記）:**
```markdown
各記憶には [certainty: X, time: Y, source: Z, kind: W] の注釈が付いています。
自然な想起表現のために以下を参考にしてください：
- certainty=confident → 確信を持って想起
- certainty=tentative → 「たしか〜」「I think〜」など控えめに
- certainty=vague → 「〜気がする」「maybe〜」など曖昧に
- certainty=forgotten → 言及しない（should_mention=false）
- time_hint=distant → 「昔」「long ago」など時間的距離を表現
- source_hint=llm_inferred → user_stated より控えめに
- source_hint=reflected → 「考えてみると〜」など洞察として表現

表現はあなた（{persona}）の自然な口調に合わせてください。
これらの注釈の文言自体を出力してはいけません。
```

---

### Task 4.1: RecallAnnotator — 記憶にメタデータ注釈を付与

**背景:** 確信度、経過時間、情報源などの数値データを、LLM が解釈可能な言語非依存のヒント文字列に変換する。

**設計上の注意:**
- このモジュールには**日本語・英語・特定ペルソナの文字列を一切含まない**。
- 出力は全て機械可読な enum 値（`"confident"`, `"days_7"` 等）。
- 文章化は LLM の責務。

**Files:**
- Create: `nous/domain/memory/recall_annotator.py`
- Test: `tests/unit/test_recall_annotator.py` (新規)

- [ ] **Step 1: RecallAnnotation データクラス + RecallAnnotator 実装**

```python
# nous/domain/memory/recall_annotator.py
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Certainty = Literal["confident", "tentative", "vague", "forgotten"]
TimeHint = Literal["recent", "days_7", "days_30", "days_90", "years"]
SourceHint = Literal["user_stated", "llm_inferred", "reflected", "consolidated", "tool_output"]
KindHint = Literal["episodic", "semantic", "procedural", "prospective"]

@dataclass(frozen=True)
class RecallAnnotation:
    """言語・ペルソナ非依存の記憶想起メタデータ。
    LLM がこの注釈を見て、自分のペルソナ口調で自然な想起表現を生成する。"""
    certainty: Certainty
    time_hint: TimeHint
    source_hint: SourceHint
    kind_hint: KindHint
    should_mention: bool


class RecallAnnotator:
    """記憶の confidence, age, source_type, kind から RecallAnnotation を生成。"""

    CERTAINTY_THRESHOLDS = [
        (0.8, "confident"),
        (0.5, "tentative"),
        (0.2, "vague"),
        (float("-inf"), "forgotten"),
    ]

    TIME_BUCKETS = [
        (1, "recent"),     # <1日
        (7, "days_7"),     # <1週間
        (30, "days_30"),   # <1ヶ月
        (90, "days_90"),   # <3ヶ月
        (float("inf"), "years"),
    ]

    def annotate(
        self,
        confidence: float,
        age_days: float,
        source_type: str = "user_stated",
        kind: str = "semantic",
    ) -> RecallAnnotation:
        return RecallAnnotation(
            certainty=self._compute_certainty(confidence, age_days),
            time_hint=self._compute_time_hint(age_days),
            source_hint=self._normalize_source(source_type),
            kind_hint=self._normalize_kind(kind),
            should_mention=self._should_mention(confidence, age_days),
        )

    def _compute_certainty(self, confidence: float, age_days: float) -> Certainty:
        # 90日以上経過で確信度を 0.1 下げる（Bartlett 1932 の記憶減衰）
        effective = confidence - (0.1 if age_days > 90 else 0.0)
        for threshold, label in self.CERTAINTY_THRESHOLDS:
            if effective >= threshold:
                return label
        return "forgotten"

    def _compute_time_hint(self, age_days: float) -> TimeHint:
        for boundary, label in self.TIME_BUCKETS:
            if age_days < boundary:
                return label
        return "years"

    def _normalize_source(self, raw: str) -> SourceHint:
        valid = {"user_stated", "user_implied", "llm_inferred", "tool_output", "consolidated", "reflected"}
        return raw if raw in valid else "user_stated"

    def _normalize_kind(self, raw: str) -> KindHint:
        valid = {"episodic", "semantic", "procedural", "prospective"}
        return raw if raw in valid else "semantic"

    def _should_mention(self, confidence: float, age_days: float) -> bool:
        """完全忘却の記憶は発話対象外"""
        return self._compute_certainty(confidence, age_days) != "forgotten"
```

- [ ] **Step 2: テスト**

```python
# tests/unit/test_recall_annotator.py
from datetime import datetime, timezone, timedelta
from nous.domain.memory.recall_annotator import RecallAnnotator, RecallAnnotation

def test_confident_fresh_memory():
    ann = RecallAnnotator().annotate(confidence=0.95, age_days=0.5)
    assert ann.certainty == "confident"
    assert ann.time_hint == "recent"
    assert ann.should_mention is True

def test_tentative_aged_memory():
    ann = RecallAnnotator().annotate(confidence=0.85, age_days=100)
    assert ann.certainty == "tentative"  # 0.85 - 0.1 = 0.75 → tentative
    assert ann.time_hint == "years"
    assert ann.should_mention is True

def test_vague_low_confidence():
    ann = RecallAnnotator().annotate(confidence=0.35, age_days=5)
    assert ann.certainty == "vague"
    assert ann.should_mention is True

def test_forgotten_very_low_confidence():
    ann = RecallAnnotator().annotate(confidence=0.1, age_days=200)
    assert ann.certainty == "forgotten"
    assert ann.should_mention is False

def test_time_buckets():
    ann = RecallAnnotator()
    assert ann.annotate(0.9, 0.5).time_hint == "recent"
    assert ann.annotate(0.9, 5).time_hint == "days_7"
    assert ann.annotate(0.9, 20).time_hint == "days_30"
    assert ann.annotate(0.9, 60).time_hint == "days_90"
    assert ann.annotate(0.9, 200).time_hint == "years"

def test_source_kind_passthrough():
    ann = RecallAnnotator().annotate(0.9, 1.0, source_type="reflected", kind="episodic")
    assert ann.source_hint == "reflected"
    assert ann.kind_hint == "episodic"

def test_invalid_source_defaults():
    ann = RecallAnnotator().annotate(0.9, 1.0, source_type="garbage")
    assert ann.source_hint == "user_stated"

def test_annotation_is_frozen():
    ann = RecallAnnotation(certainty="confident", time_hint="recent",
                           source_hint="user_stated", kind_hint="semantic",
                           should_mention=True)
    try:
        ann.certainty = "vague"  # type: ignore
        assert False, "Should raise FrozenInstanceError"
    except Exception:
        pass
```

```bash
pytest tests/unit/test_recall_annotator.py -v
```

- [ ] **Step 3: コミット**

```bash
git commit -m "feat: RecallAnnotator — language-agnostic memory metadata hints for LLM expression"
```

---

### Task 4.2: RecallGovernor — 自発想起の頻度制限 + パイプライン統合

**背景:** 記憶の洪水を防ぐための純粋な頻度制限ロジック。言語・ペルソナ非依存。

**パイプライン統合ポイント:**
```
ChatService.chat() 開始時
  └── governor = RecallGovernor()  ← 会話セッションごとに新規生成
PrepareStep._search_memories() 後
  └── if governor.may_recall(turn=..., is_user_speaking=...):
          related_memories をコンテキストに注入
          governor.record_recall(turn)
会話終了時
  └── governor.reset()  ← または次会話開始時に新規生成
```

**設計上の注意:**
- このモジュールは純粋なカウンター + 判定ロジックのみを含む。
- トリガー検出（「覚えてる？」に反応等）は**実装しない**。検索エンジンの埋め込み類似度が事実上のトリガーになる。

**Files:**
- Create: `nous/domain/memory/recall_governor.py`
- Modify: `nous/application/chat/service.py` — RecallGovernor の生成・保持
- Modify: `nous/application/chat/pipeline/prepare.py` — 記憶注入前に `may_recall()` チェック
- Test: `tests/unit/test_recall_governor.py` (新規)

- [ ] **Step 1: RecallGovernor 実装**

```python
# nous/domain/memory/recall_governor.py
class RecallGovernor:
    """自発想起の洪水を防ぐ頻度制限。"""
    
    MAX_SPONTANEOUS = 3    # 1会話あたり最大3回
    MIN_TURN_GAP = 2       # 最低2ターンの間隔を空ける

    def __init__(self):
        self._count = 0
        self._last_turn = -1

    def may_recall(self, current_turn: int, is_user_speaking: bool) -> bool:
        if self._count >= self.MAX_SPONTANEOUS:
            return False
        if current_turn - self._last_turn < self.MIN_TURN_GAP:
            return False
        if is_user_speaking:
            return False  # ユーザー発話中は想起しない
        return True

    def record_recall(self, turn: int):
        self._count += 1
        self._last_turn = turn

    def reset(self):
        self._count = 0
        self._last_turn = -1
```

- [ ] **Step 2: テスト**

```python
# tests/unit/test_recall_governor.py
from nous.domain.memory.recall_governor import RecallGovernor

def test_allows_first_recall():
    gov = RecallGovernor()
    assert gov.may_recall(0, is_user_speaking=False)

def test_blocks_consecutive_recalls():
    gov = RecallGovernor()
    gov.record_recall(0)
    assert not gov.may_recall(1, is_user_speaking=False)

def test_allows_after_gap():
    gov = RecallGovernor()
    gov.record_recall(0)
    assert gov.may_recall(2, is_user_speaking=False)

def test_blocks_when_user_speaking():
    gov = RecallGovernor()
    assert not gov.may_recall(0, is_user_speaking=True)

def test_respects_max_limit():
    gov = RecallGovernor()
    for t in (0, 2, 4):
        gov.record_recall(t)
    assert not gov.may_recall(6, is_user_speaking=False)

def test_reset_clears_state():
    gov = RecallGovernor()
    gov.record_recall(0)
    gov.record_recall(2)
    gov.reset()
    assert gov.may_recall(0, is_user_speaking=False)
```

```bash
pytest tests/unit/test_recall_governor.py -v
```

- [ ] **Step 3: コミット**

```bash
git commit -m "feat: RecallGovernor — language-agnostic spontaneous recall frequency limiter"
```

---

### Task 4.3: システムプロンプトに注釈の使い方指示を追加

**背景:** LLM が `RecallAnnotation` を受け取ったときに自然な想起表現を生成できるよう、コンテキスト構築時にガイドラインを付与する。言語・ペルソナ非依存のメタ指示。

**Files:**
- Modify: `nous/application/chat/pipeline/prepare.py` — システムプロンプトに注釈ガイドライン追記
- Test: `tests/unit/test_chat_pipeline.py` (既存テストの更新)

- [ ] **Step 1: 注釈ガイドラインプロンプトを prepare.py に追加**

```python
# nous/application/chat/pipeline/prepare.py

RECALL_ANNOTATION_GUIDELINES = """
## Memory Recall Annotations
Each recalled memory includes annotations: [certainty: X, time: Y, source: Z, kind: W].
Use these as hints for natural recall expression — not as literal text to output.

(Examples below include English and Japanese phrases for multilingual reference.
Use whichever matches your persona's natural language — never copy-paste.)

### Certainty hints:
- confident → Recall with assertion. No hedging needed.
- tentative → Use hedging: "I think...", "たしか...", etc. in your persona's voice.
- vague → Use stronger hedging: "I vaguely remember...", "〜だった気がする...", etc.
- forgotten → Do NOT mention this memory (should_mention is false).

### Time hints:
- recent / days_7 → "just now", "the other day", "さっき", "この前"
- days_30 → "a while ago", "こないだ"
- days_90 → "a few months back", "前に"
- years → "long ago", "昔"

### Source hints:
- user_stated → Recall with confidence (user said it directly).
- llm_inferred → Slightly hedged (inferred, not explicitly stated).
- reflected → Express as an insight: "Thinking about it...", "考えてみると..."
- consolidated → Express as a summary of multiple memories.

### Kind hints:
- episodic → Include time/place context if available.
- semantic → State as fact or preference.
- prospective → Frame as future intention or reminder.

IMPORTANT:
- Express everything naturally in your persona's voice.
- NEVER output the annotation labels themselves (e.g., do not say "[certainty: confident]").
- NEVER say "database", "retrieved", "record", "search result" or any technical term.
"""
```

- [ ] **Step 2: prepare.py のコンテキスト構築に注釈を統合**

既存の `_build_system_prompt()` / `_build_context_section()` に、memory list の各エントリに annotation を付与する処理を追加:

```python
# prepare.py — 記憶をコンテキスト化する際に注釈を付与
def _format_memory_with_annotation(memory, annotation: RecallAnnotation) -> str:
    if not annotation.should_mention:
        return ""  # サイレント忘却
    hints = f"[certainty: {annotation.certainty}, time: {annotation.time_hint}, "
    hints += f"source: {annotation.source_hint}, kind: {annotation.kind_hint}]"
    return f"{hints} {memory.content}"
```

- [ ] **Step 3: テスト更新**

既存の `test_chat_pipeline.py` で、memory formatting に注釈が付与されることを確認:

```python
def test_memory_format_includes_annotations():
    annotator = RecallAnnotator()
    ann = annotator.annotate(confidence=0.95, age_days=1, kind="episodic")
    result = _format_memory_with_annotation(mock_memory, ann)
    assert "[certainty: confident" in result
    assert "time: recent" in result
    assert "kind: episodic" in result

def test_forgotten_memory_not_formatted():
    ann = RecallAnnotator().annotate(confidence=0.1, age_days=365)
    result = _format_memory_with_annotation(mock_memory, ann)
    assert result == ""  # should_mention=false
```

```bash
pytest tests/unit/test_chat_pipeline.py -v
```

- [ ] **Step 4: コミット**

```bash
git commit -m "feat: integrate RecallAnnotation into context building + LLM guidance prompt"
```

---

## Chunk 5: 最終検証 + 統合テスト

### Task 5.1: 全テストスイート実行 + 検証

- [ ] **Step 1: ユニットテスト全実行**

```bash
pytest tests/unit/ -v --tb=short
```

- [ ] **Step 2: 統合テスト実行**

```bash
pytest tests/integration/ -v --tb=short
```

- [ ] **Step 3: カバレッジ確認**

```bash
pytest tests/ --cov=nous --cov-report=term --cov-fail-under=62
```

- [ ] **Step 4: lint + type check + security**

```bash
ruff check nous/ tests/
ruff format --check nous/ tests/
mypy nous/ --ignore-missing-imports
bandit -r nous/ -ll
```

- [ ] **Step 5: ドキュメント更新**

```bash
# .spec/TODO-v4.md に全タスクの完了を記録
# .spec/KNOWLEDGE.md に学びを追記
# docs/llm_usage_guide.md に新機能 (kind, hedging, reflection) を追記
```

- [ ] **Step 6: 最終コミット**

```bash
git add -A
git commit -m "feat: human-like memory reform — kind, links, SA, reflection, hedging, triggers"
git push origin main
```

---

## 補足: 別 PR に分離するタスク

以下のタスクは本改革とは独立しており、別途ハウスキーピング PR として扱う:

- **MCP 2026-07-28 spec 対応**（lifespan context manager, Last-Event-ID, MRTR 移行計画）
- **ComfyUI /history → /api/jobs 移行**（deprecated API の更新）
- **IntimacyGate（親密さゲート）** — 親密度を計測する機構が先に必要。今回のスコープ外
- **Conway SMS 3層階層**（lifetime_periods / general_events） — データが成熟してから着手
- **Narrative weaving**（記憶の物語化） — reflection の動作確認後
- **flashbulb_marker / suppressed カラム** — valence + emotion bias の効果検証後
- **TriggerDetector**（言語固有 regex） — 検索エンジンの埋め込み類似度が事実上のトリガー。言語非依存な実装が可能になった時点で再検討
- **IntimacyGate**（親密さゲート） — 親密度計測機構が先に必要。今回スコープ外
