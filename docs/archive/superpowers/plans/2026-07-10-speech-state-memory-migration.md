# Speech/Physical/Mental → Memories Tag-Based + One-Shot Consumption

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** speech_style, physical_state, mental_state の3状態を context_state 永続保存から memories タグベース + ワンショット消費方式に移行。別セッションに1回だけ反映され、Ebbinghaus 忘却曲線で自然減衰する。

**Architecture:**
- memories テーブルに `last_consumed_at TIMESTAMP` カラムを追加（アトミック消費管理）
- MemoryLLM が変化を検出 → `["speech_style"]` / `["physical_state"]` / `["mental_state"]` タグ付き memory として保存
- get_context() が `last_consumed_at IS NULL` の最新 memory を読み込み → `UPDATE ... SET last_consumed_at = now()` で1クエリ消費
- 次回以降の get_context() は `last_consumed_at >= created_at` でスキップ
- WebUI は `last_consumed_at` を無視して全メモリを表示（最新状態として）

**Tech Stack:** Python (memory_llm.py, _tools_helpers.py, _tools_persona.py, prepare.py), JavaScript (overview.js)

---

## 変更後フロー

```
[LLM会話] → MemoryLLM が変化検出 → memory 作成(tags=["speech_style"], last_consumed_at=NULL)
[get_context()] → tag=["speech_style"] + last_consumed_at IS NULL で最新 memory 検索
  → コンテキスト注入 → UPDATE SET last_consumed_at = now()（1クエリ、アトミック）
[次回 get_context()] → last_consumed_at が入ったメモリはスキップ
[LLMが新たな変化検出] → 新しい memory 作成（last_consumed_at=NULL → 次回の get_context で拾われる）
[WebUI] → tag=["speech_style"] で全 memory 検索 → 最新を表示（last_consumed_at 無視）
```

---

## Chunk 1: DB スキーマ — last_consumed_at カラム追加 + Protocol 更新

### Task 1.1: memories テーブルに last_consumed_at カラム追加

**Files:**
- Modify: `nous/infrastructure/sqlite/connection.py` (L11-46, _MEMORY_SCHEMA)
- Modify: `nous/domain/memory/entities.py` (Memory エンティティ)

- [ ] **Step 1: スキーマ変更**

`_MEMORY_SCHEMA` の memories テーブル定義に以下を追加:

```sql
last_consumed_at TEXT
```

`lifecycle_status TEXT` 行の直後に追加（L33付近）。

- [ ] **Step 2: Memory エンティティ更新**

```python
@dataclass
class Memory:
    # ... existing fields ...
    last_consumed_at: datetime | None = None  # ワンショット消費用
```

- [ ] **Step 3: 既存DB自動マイグレーション**

`connection.py` の `initialize_schema()` 内で、`last_consumed_at` カラムが存在しない場合に ALTER TABLE する try/except を追加（1行のみ、削除予定の一時コード）。

```python
with suppress(Exception):
    conn.execute("ALTER TABLE memories ADD COLUMN last_consumed_at TEXT")
```

- [ ] **Step 4: コミット**

```bash
git add nous/infrastructure/sqlite/connection.py nous/domain/memory/entities.py
git commit -m "feat(memory): add last_consumed_at column for one-shot state consumption"
```

### Task 1.2: MemoryRepository Protocol + 実装更新

**Files:**
- Modify: `nous/domain/memory/repository.py` (Protocol)
- Modify: `nous/infrastructure/sqlite/memory_repo.py` (実装)

- [ ] **Step 1: Protocol に consume メソッド追加**

```python
def consume_memory(self, key: str) -> Result[None, RepositoryError]:
    """Mark a memory as consumed (set last_consumed_at = now). Atomic, single-query."""
    ...
```

- [ ] **Step 2: 実装クラスに consume メソッド追加**

```python
def consume_memory(self, key: str) -> Result[None, RepositoryError]:
    """Set last_consumed_at = now() for a memory."""
    try:
        self._execute(
            "UPDATE memories SET last_consumed_at = ? WHERE key = ?",
            (datetime.now(UTC).isoformat(), key),
        )
        return Success(None)
    except Exception as e:
        return Failure(RepositoryError(str(e)))
```

- [ ] **Step 3: get_by_tags に include_consumed パラメータ追加**

```python
def get_by_tags(
    self,
    tags: list[str],
    include_consumed: bool = False,  # False = 未消費のみ
    limit: int = 10,
) -> list[Memory]:
```

未消費フィルタ: `AND (last_consumed_at IS NULL)` を WHERE 句に追加。

- [ ] **Step 4: memory_repo の SELECT クエリに last_consumed_at カラム追加**

get() メソッドの SELECT に `last_consumed_at` を追加し、Memory オブジェクト構築時にマッピング。

- [ ] **Step 5: テスト**

```python
def test_consume_memory_sets_last_consumed_at(memory_repo):
    key = memory_repo.save("test", tags=["speech_style"])
    result = memory_repo.consume_memory(key)
    assert result.is_ok
    mem = memory_repo.get(key).value
    assert mem.last_consumed_at is not None

def test_get_by_tags_excludes_consumed(memory_repo):
    key1 = memory_repo.save("古い状態", tags=["speech_style"])
    key2 = memory_repo.save("新しい状態", tags=["speech_style"])
    memory_repo.consume_memory(key2)
    results = memory_repo.get_by_tags(["speech_style"], include_consumed=False)
    assert len(results) == 1
    assert results[0].content == "古い状態"

def test_get_by_tags_include_consumed(memory_repo):
    key1 = memory_repo.save("s1", tags=["speech_style"])
    memory_repo.consume_memory(key1)
    results = memory_repo.get_by_tags(["speech_style"], include_consumed=True)
    assert len(results) == 1  # consumed も含まれる
```

- [ ] **Step 6: コミット**

```bash
git add nous/domain/memory/repository.py nous/infrastructure/sqlite/memory_repo.py
git commit -m "feat(memory): add consume_memory + include_consumed filter for one-shot patterns"
```

---

## Chunk 2: MemoryLLM — speech_style/physical_state/mental_state を memory 化

### Task 2.1: プロンプト変更（確認）

**Files:**
- Verify: `nous/application/chat/memory_llm.py` L83-89

既に適用済みの以下プロンプトを確認:
```
- 口調変化: speech_style（私の話し方・口調が大きく変わった時のみ記録）
```

不足があれば追記。

### Task 2.2: ハンドラ変更 — context_state 保存 → memory 保存

**Files:**
- Modify: `nous/application/chat/memory_llm.py` L383-398 (context_update ハンドラ)
- Test: `tests/unit/test_memory_llm.py`

- [ ] **Step 1: テストを書く**

```python
@pytest.mark.asyncio
async def test_context_update_creates_speech_style_memory(mock_ctx, mock_config):
    """context_update の speech_style が memory として保存され、context_state には送られない"""
    from nous.application.chat.memory_llm import MemoryLLM
    llm = MemoryLLM(mock_ctx, mock_config, persona="herta")
    result = {
        "context_update": {
            "speech_style": "ツンデレ口調",
            "emotion": "joy",  # emotion は引き続き context_state へ
        }
    }
    await llm._apply_context_update(result, persona="herta")
    # speech_style → memory 確認
    mock_ctx.memory_service.create_memory.assert_any_call(
        content="speech_style: ツンデレ口調",
        tags=["speech_style", "speech"],
        importance=0.6,
    )
    # emotion → context_state 確認（既存動作、変更なし）
    mock_ctx.persona_service.update_emotion.assert_called_once()

@pytest.mark.asyncio
async def test_context_update_no_state_change_skips_memory(mock_ctx, mock_config):
    """変化がない場合、memory は作成されない"""
    llm = MemoryLLM(mock_ctx, mock_config, persona="herta")
    result = {"context_update": {}}  # 空
    await llm._apply_context_update(result, persona="herta")
    mock_ctx.memory_service.create_memory.assert_not_called()

@pytest.mark.asyncio
async def test_context_update_none_state_skips_memory(mock_ctx, mock_config):
    """状態が None に戻るケースでも memory 作成（解除を記録）"""
    llm = MemoryLLM(mock_ctx, mock_config, persona="herta")
    result = {"context_update": {"speech_style": None}}
    await llm._apply_context_update(result, persona="herta")
    mock_ctx.memory_service.create_memory.assert_not_called()  # None は無視
```

- [ ] **Step 2: 実装**

`memory_llm.py` の context_update 処理で、`speech_style`, `physical_state`, `mental_state` を `update_physical_state()` の `allowed_keys` から**除外**し、代わりに memory として保存:

```python
# speech_style/physical_state/mental_state → memories (one-shot)
for key, tags in [
    ("speech_style", ["speech_style", "speech"]),
    ("physical_state", ["physical_state", "body"]),
    ("mental_state", ["mental_state", "mind"]),
]:
    val = ctx_update.get(key)
    if val is not None and str(val).strip():
        ctx.memory_service.create_memory(
            content=f"{key}: {val}",
            tags=tags,
            importance=0.6,
        )
        # key を ctx_update から除去 → update_physical_state に渡さない
        ctx_update.pop(key, None)

# 残りの state フィールドは context_state へ（emotion, fatigue, warmth, etc.）
# 既存の update_physical_state ロジックはそのまま
```

- [ ] **Step 3: テストパス確認**

```bash
pytest tests/unit/test_memory_llm.py -v
```

- [ ] **Step 4: コミット**

```bash
git add nous/application/chat/memory_llm.py tests/unit/test_memory_llm.py
git commit -m "feat(memory_llm): store speech_style/physical_state/mental_state as memories instead of context_state"
```

---

## Chunk 3: get_context — memory 読み込み + ワンショット消費

### Task 3.1: _format_lightweight_response から context_state 参照を削除

**Files:**
- Modify: `nous/api/mcp/_tools_helpers.py` L38-45, L143-144, L198-201
- Modify: `nous/application/chat/pipeline/prepare.py` L294-298, L307

- [ ] **Step 1: _format_state_block 修正（L38-45）**

`speech_style`, `physical_state`, `mental_state` の行を削除（memory 経由で注入するため）。

- [ ] **Step 2: _format_lightweight_response L143-144 削除**

`🗣️ REMEMBER — Your speaking style:` 行を削除。

- [ ] **Step 3: L198-201 の state_parts も修正**

`state.physical_state` と `state.mental_state` の行を削除（プランでは見逃されていた二重表示バグ）。

- [ ] **Step 4: prepare.py 修正**

L294-298 (`mental_state`, `speech_style`), L307 (`physical_state`) の注入を削除。

- [ ] **Step 5: コミット**

```bash
git add nous/api/mcp/_tools_helpers.py nous/application/chat/pipeline/prepare.py
git commit -m "refactor: remove speech_style/physical_state/mental_state from context_state injection paths"
```

### Task 3.2: get_context に memory ベースの状態読み込み + 消費機能追加

**Files:**
- Modify: `nous/api/mcp/_tools_persona.py` (get_context 関数)
- Test: `tests/unit/test_tools_persona.py`

- [ ] **Step 1: テストを書く**

```python
@pytest.mark.asyncio
async def test_get_context_reads_speech_style_memory(mock_ctx):
    """get_context が speech_style メモリを読み込み、消費する"""
    mem = _make_memory(
        key="mem_speech_1",
        content="speech_style: ツンデレ口調",
        tags=["speech_style", "speech"],
        created_at=datetime(2026, 7, 10, 12, 0),
    )
    mock_ctx.memory_service.get_by_tags.return_value = [mem]
    result = await _tool_get_context(mock_ctx, "herta")
    assert "ツンデレ口調" in result
    mock_ctx.memory_repo.consume_memory.assert_called_once_with("mem_speech_1")

@pytest.mark.asyncio
async def test_get_context_skips_consumed_memories(mock_ctx):
    """consumed 済みメモリはスキップされる"""
    # get_by_tags は include_consumed=False → 空リスト
    mock_ctx.memory_service.get_by_tags.return_value = []
    result = await _tool_get_context(mock_ctx, "herta")
    # 口調関連の注入がないことを確認
    assert "speech_style" not in result.lower() or "🗣️" not in result

@pytest.mark.asyncio
async def test_get_context_consume_failure_handles_gracefully(mock_ctx):
    """consume が失敗しても get_context はクラッシュしない"""
    mem = _make_memory(key="mem_s1", content="speech_style: test", tags=["speech_style"])
    mock_ctx.memory_service.get_by_tags.return_value = [mem]
    mock_ctx.memory_repo.consume_memory.side_effect = Exception("DB error")
    result = await _tool_get_context(mock_ctx, "herta")
    # コンテキストは返す（データロスより表示を優先）
    assert "test" in result

@pytest.mark.asyncio
async def test_get_context_multiple_unconsumed_picks_latest(mock_ctx):
    """未消費メモリが複数ある場合、最新の1件のみを消費"""
    mem_old = _make_memory(key="mem_old", content="古い口調", tags=["speech_style"], created_at=datetime(2026, 7, 9))
    mem_new = _make_memory(key="mem_new", content="新しい口調", tags=["speech_style"], created_at=datetime(2026, 7, 10))
    mock_ctx.memory_service.get_by_tags.return_value = [mem_old, mem_new]
    await _tool_get_context(mock_ctx, "herta")
    # 最新のみ消費
    mock_ctx.memory_repo.consume_memory.assert_called_once_with("mem_new")
```

- [ ] **Step 2: 実装**

`_tool_get_context()` 内で、context formatting の前に以下を追加:

```python
# Read one-shot state memories (speech_style/physical_state/mental_state)
one_shot_context: dict[str, str] = {}
for tag_name, label in [
    ("speech_style", "🗣️ 口調"),
    ("physical_state", "💪 身体状態"),
    ("mental_state", "🧠 精神状態"),
]:
    mems = ctx.memory_service.get_by_tags([tag_name], include_consumed=False, limit=5)
    if mems:
        latest = sorted(mems, key=lambda m: m.created_at or datetime.min, reverse=True)[0]
        one_shot_context[label] = latest.content
        # Mark consumed (atomic, single query). Failure is swallowed — data loss is worse than double-display.
        ctx.memory_repo.consume_memory(latest.key)
```

フォーマッタ呼び出し時に `one_shot_context` を追加の引数として渡す。

- [ ] **Step 3: _format_lightweight_response のシグネチャ更新**

```python
def _format_lightweight_response(
    state: PersonaState,
    time_since: str = "",
    current_time: str = "",
    decay_note: str | None = None,
    top_memories: list[Memory] | None = None,
    goals: list[Memory] | None = None,
    body_state_history: list[BodyStateRecord] | None = None,
    one_shot_context: dict[str, str] | None = None,  # NEW
) -> str:
```

フォーマット内で `one_shot_context` の内容を注入:

```python
if one_shot_context:
    lines.append("\n【前回セッションからの状態】")
    for label, content in one_shot_context.items():
        lines.append(f"  {label}: {content}")
```

- [ ] **Step 4: テストパス確認**

```bash
pytest tests/unit/test_tools_persona.py -v
```

- [ ] **Step 5: コミット**

```bash
git add nous/api/mcp/_tools_persona.py nous/api/mcp/_tools_helpers.py tests/unit/test_tools_persona.py
git commit -m "feat(get_context): read speech_style/physical_state/mental_state from memories with one-shot consumption"
```

---

## Chunk 4: 移行戦略 — 既存 context_state データの移行

### Task 4.1: 起動時マイグレーションスクリプト

**Files:**
- Create: `nous/infrastructure/sqlite/migration_one_shot.py` (一時的、次のリリースで削除)
- Modify: `nous/infrastructure/sqlite/connection.py` (initialize_schema 内で呼び出し)

- [ ] **Step 1: マイグレーション関数作成**

```python
def _migrate_context_state_to_memories(conn: sqlite3.Connection, persona: str, persona_id: int) -> None:
    """One-shot: migrate existing context_state speech/physical/mental to memories.
    
    Reads context_state WHERE key IN ('speech_style','physical_state','mental_state'),
    creates corresponding memory records with tags, then leaves context_state intact
    (for webui backward compatibility during transition period).
    """
    state_map = {
        "speech_style": (["speech_style", "speech"], "speech_style"),
        "physical_state": (["physical_state", "body"], "physical_state"),
        "mental_state": (["mental_state", "mind"], "mental_state"),
    }
    for state_key, (tags, content_prefix) in state_map.items():
        row = conn.execute(
            "SELECT value, updated_at FROM context_state WHERE persona = ? AND key = ? ORDER BY updated_at DESC LIMIT 1",
            (persona, state_key),
        ).fetchone()
        if row and row[0]:
            # Create as consumed so it doesn't auto-inject on first get_context
            conn.execute(
                """INSERT INTO memories (key, content, tags, importance, created_at, last_consumed_at)
                   VALUES (?, ?, ?, 0.6, ?, ?)""",
                (
                    f"mig_one_shot_{persona_id}_{state_key}",
                    f"{content_prefix}: {row[0]}",
                    json.dumps(tags),
                    row[1] or datetime.now(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),  # consumed → never auto-injected
                ),
            )
```

- [ ] **Step 2: 呼び出し**

`connection.py` の `initialize_schema(persona)` 内で、`last_consumed_at` の ALTER TABLE 後に呼び出す。

- [ ] **Step 3: コミット（[skip-docs]）**

```bash
git add nous/infrastructure/sqlite/migration_one_shot.py nous/infrastructure/sqlite/connection.py
git commit -m "feat(migration): one-shot migration of context_state to memories [skip-docs]"
```

### Task 4.2: WebUI フォールバック（移行期間中）

**Files:**
- Modify: `nous/api/http/static/overview.js` L361-364
- Modify: `nous/api/http/routers/persona.py`

- [ ] **Step 1: REST API に state_memories 追加**

`get_dashboard()` に以下を追加:

```python
# State memories (speech/physical/mental) — newest per tag
state_memories = {}
for tag in ["speech_style", "physical_state", "mental_state"]:
    mems = ctx.memory_service.get_by_tags([tag], include_consumed=True, limit=1)
    if mems:
        latest = sorted(mems, key=lambda m: m.created_at or datetime.min, reverse=True)[0]
        state_memories[tag] = {
            "content": latest.content.replace(f"{tag}: ", ""),
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        }
```

- [ ] **Step 2: overview.js でフォールバック付き表示**

```js
// 優先: state_memories, フォールバック: context_state（移行期間中）
const speechContent = state_memories?.speech_style?.content || stats.speech_style;
const physicalContent = state_memories?.physical_state?.content || ctx.physical_state;
const mentalContent = state_memories?.mental_state?.content || ctx.mental_state;
```

- [ ] **Step 3: コミット**

```bash
git add nous/api/http/routers/persona.py nous/api/http/static/overview.js
git commit -m "feat(webui): display state from memories with context_state fallback"
```

---

## Chunk 5: クリーンアップ & 検証

### Task 5.1: update_context MCP ツールから speech/physical/mental 除去

**Files:**
- Modify: `nous/api/mcp/_tools_persona.py` L145-185
- Modify: `nous/api/mcp/tools.py` L258-290

update_context ツールのパラメータから `speech_style`, `physical_state`, `mental_state` を削除（MemoryLLM が自動処理するため）。

- [ ] **Step 1: 削除**
- [ ] **Step 2: ruff check**
- [ ] **Step 3: コミット**

### Task 5.2: mental_state タグフィルタ確認

**Files:**
- Verify: `nous/api/mcp/_tools_helpers.py` L253

`if t_clean not in ("active", "cancelled", "achieved", "fulfilled", "mental_state")` の `"mental_state"` 除外が意図的か確認。context tags から除外するロジックとして残すか再検討。

### Task 5.3: PersonaState entity の非推奨化

**Files:**
- Modify: `nous/domain/persona/entities.py`

`speech_style`, `physical_state`, `mental_state` フィールドに deprecation docstring を追加:

```python
physical_state: str | None = None  # DEPRECATED: use memories tag=["physical_state"] instead
mental_state: str | None = None    # DEPRECATED: use memories tag=["mental_state"] instead
speech_style: str | None = None    # DEPRECATED: use memories tag=["speech_style"] instead
```

次のメジャーバージョンで削除予定。現時点では型チェッカーの安定性のため維持。

### Task 5.4: 全体テスト実行

- [ ] **Step 1: 全テストスイート**

```bash
pytest tests/ -x --tb=short -q
```

- [ ] **Step 2: 失敗テスト修正**

### Task 5.5: lint + type check

```bash
ruff check nous/
```

---

## 注意点

1. **emotion, fatigue, warmth, arousal, heart_rate, pain** は context_state のまま維持（数値的 body state）
2. **environment, relationship_status** も context_state のまま維持（設定値）
3. **context_note** は persona_info のまま維持（session continuity）
4. **移行スクリプト** (`migration_one_shot.py`) は次のリリースで削除予定の一時コード
5. **WebUI フォールバック**（context_state → memories）も移行完了後に memories のみに統一
6. `consume_memory` の失敗は swallowing（ログ出力のみ）。データロスより二重表示がマシという設計判断
