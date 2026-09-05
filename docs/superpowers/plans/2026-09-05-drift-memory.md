# キャラ逸脱の蓄積・傾向補正（記憶方式） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CharacterJudgeの違反判定を一人称反省文として記憶に蓄積し、次ターン以降のプロンプト想起と期限付き減衰で傾向補正する。

**Architecture:** judgeは判定専念のまま無変更。`post.py`でjudgmentをMemoryLLMのpayloadに載せ替え、MemoryLLMがfactsに反省文を1件だけ書く（tags `character_drift`+種別、importance 0.8-0.9、`valid_until`+7日）。想起は通常recall（`valid_at`付与）＋`context_loader`の直接注入の二段構え。新規スコアラ・新規列なし。

**Tech Stack:** Python (3.11+, `datetime.UTC`使用中), pytest, ruff, mypy

## Global Constraints

- `nous/application/chat/character_judge.py` は触らない（判定専念）。
- `memory_retriever.py` の重み（recency 0.3 / importance 0.3 / relevance 0.4、RRF k=5.0）は変えない（`valid_at`付与のみ）。
- 新規スコアラ・schema新規列・Author's Note復活は禁止。
- drift反省文は1ターン1件まで。violationがnone/Noneなら何も作らない。
- 表示文は「⚠ 内面に違和感(種別)」形式に統一。

---

## File Structure

- Modify: `nous/application/chat/memory_prompts.py` — `_build_drift_section()`追加＋テンプレートに`{drift_section}`とdriftルール追加。
- Modify: `nous/application/chat/memory_extractor.py` — `MemoryLLM.process()`に`drift`引数追加、`run_memory_llm()`の転送、facts保存時の`valid_until`付与。
- Modify: `nous/application/chat/pipeline/post.py` — `_with_drift()`追加＋judge→memoryの逐次配線。
- Modify: `nous/application/chat/pipeline/memory_retriever.py` — `SearchQuery`に`valid_at`付与。
- Modify: `nous/application/chat/pipeline/context_loader.py` — Tier3にdrift直接注入ブロック追加。
- Modify: `nous/api/http/static/chat/chat-core.js` — 表示名1行変更。
- Create: `tests/unit/test_character_drift.py` — 本planの全テスト。

---

### Task 1: プロンプトにdrift受け口を作る

**Files:**
- Modify: `nous/application/chat/memory_prompts.py:5-24`（テンプレート会話部）、`:58-71`（注意書き部）
- Test: `tests/unit/test_character_drift.py`

**Interfaces:**
- Consumes: なし（独立）。
- Produces: `_build_drift_section(drift: dict | None) -> str` — Task 2の`process()`が使う。`_MEMORY_LLM_PROMPT`に`{drift_section}`プレースホルダ。

- [ ] **Step 1: Write the failing test**

```python
"""Tests for character-drift accumulation (spec: 2026-09-05-drift-memory-design)."""

from __future__ import annotations

from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT, _build_drift_section


class TestDriftSection:
    def test_none_returns_empty(self):
        assert _build_drift_section(None) == ""

    def test_violation_renders_type_and_detail(self):
        section = _build_drift_section({"violation": "tone", "detail": "一人称が俺だった"})
        assert "tone" in section
        assert "一人称が俺だった" in section

    def test_template_has_placeholder(self):
        assert "{drift_section}" in _MEMORY_LLM_PROMPT

    def test_template_has_drift_rule(self):
        assert "character_drift" in _MEMORY_LLM_PROMPT
```

Run: `pytest tests/unit/test_character_drift.py -v`
Expected: FAIL with "cannot import name '_build_drift_section'"

- [ ] **Step 2: Implement minimal code**

`memory_prompts.py`の`_MEMORY_LLM_PROMPT`定義の直前に追加：

```python
def _build_drift_section(drift: dict | None) -> str:
    """キャラ一貫性監査の指摘をMemoryLLMプロンプト用の追記ブロックに変換する。"""
    if not drift or drift.get("violation") in (None, "none"):
        return ""
    violation = str(drift.get("violation", ""))
    detail = str(drift.get("detail", ""))
    return f"【キャラ一貫性監査の指摘】\n- 種別: {violation}\n- 詳細: {detail}\n"
```

テンプレートの会話部を変更（`{assistant_response}`の直後に1行追加）：

```
[assistant（私={persona_name}）]: {assistant_response}
{drift_section}
【出力形式】
```

注意書きのfacts行（`- facts は私（{persona_name}）の一人称視点で記録する…`）の直後に追加：

```
- drift: 上に【キャラ一貫性監査の指摘】がある場合のみ、反省文をfactsに1件だけ作る。
  - contentは私（{persona_name}）の一人称独白の反省文（「私は〜すべきだった」形式）。
  - tagsは ["character_drift", 指摘の種別]、importanceは0.8-0.9。
  - 指摘がなければ作らない（重複禁止）。
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/unit/test_character_drift.py -v`
Expected: PASS (4 passed)

- [ ] **Step 4: Commit**

```bash
git add nous/application/chat/memory_prompts.py tests/unit/test_character_drift.py
git commit -m "feat(drift): MemoryLLMプロンプトにdrift受け口を追加"
```

---

### Task 2: MemoryLLMにdriftを転送し、期限付きで保存する

**Files:**
- Modify: `nous/application/chat/memory_extractor.py:1-21`（import）、`:27-38`（`process`署名）、`:57-66`（prompt format）、`:245-268`（`run_memory_llm`）、`:287-292`（facts保存）
- Test: `tests/unit/test_character_drift.py`（追記）

**Interfaces:**
- Consumes: Task 1の`_build_drift_section`、`{drift_section}`。
- Produces: `process(..., drift: dict | None = None)`、`run_memory_llm`の`payload["drift"]`転送。Task 3の`post.py`が`payload["drift"]`にjudgmentを載せる。

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_drift.py`に追記：

```python
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.memory_extractor import run_memory_llm
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _make_ctx():
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.vector_store = None
    ctx.search_engine.search = AsyncMock(return_value=MagicMock(is_ok=False))
    mem = MagicMock()
    mem.key = "mem_test"
    mem.content = "dummy"
    ctx.memory_service.create_memory = AsyncMock(return_value=Success(mem))
    ctx.memory_service.get_by_tags = MagicMock(return_value=MagicMock(is_ok=False, value=[]))
    ctx.persona_service.get_context = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.search_items = MagicMock(return_value=MagicMock(is_ok=False))
    return ctx


def _make_config():
    config = MagicMock()
    config.extract_model = ""
    config.get_effective_api_key.return_value = "key"
    config.get_effective_model.return_value = "model"
    return config


class TestDriftForwarding:
    @pytest.mark.asyncio
    async def test_run_memory_llm_forwards_drift(self):
        ctx, config = _make_ctx(), _make_config()
        drift = {"violation": "tone", "detail": "一人称が俺だった"}
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value={}),
            ) as mock_process,
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a", "drift": drift})
        assert mock_process.await_args.kwargs["drift"] == drift

    @pytest.mark.asyncio
    async def test_run_memory_llm_no_drift_defaults_none(self):
        ctx, config = _make_ctx(), _make_config()
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value={}),
            ) as mock_process,
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        assert mock_process.await_args.kwargs["drift"] is None

    @pytest.mark.asyncio
    async def test_drift_fact_saved_with_valid_until(self):
        ctx, config = _make_ctx(), _make_config()
        result = {
            "facts": [
                {
                    "content": "私は一人称を間違えた。次は私で通すべきだった。",
                    "importance": 0.85,
                    "tags": ["character_drift", "tone"],
                    "emotion": "neutral",
                }
            ],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value=result),
            ),
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert kwargs["tags"] == ["character_drift", "tone"]
        assert kwargs["importance"] == 0.85
        valid_until = kwargs["valid_until"]
        delta = valid_until - get_now()
        assert timedelta(days=6) < delta <= timedelta(days=7, seconds=60)

    @pytest.mark.asyncio
    async def test_normal_fact_saved_without_valid_until(self):
        ctx, config = _make_ctx(), _make_config()
        result = {
            "facts": [{"content": "ユーザーは猫が好き", "importance": 0.7, "tags": ["preference"], "emotion": "joy"}],
            "goals": [],
            "promises": [],
            "context_update": {},
            "inventory_update": {},
        }
        with (
            patch(
                "nous.application.chat.memory_extractor._build_memory_llm_context",
                new=AsyncMock(return_value=("c", "cm", "i")),
            ),
            patch(
                "nous.application.chat.memory_extractor.MemoryLLM.process",
                new=AsyncMock(return_value=result),
            ),
        ):
            await run_memory_llm(ctx, config, {"user": "u", "assistant": "a"})
        kwargs = ctx.memory_service.create_memory.await_args.kwargs
        assert "valid_until" not in kwargs
```

Run: `pytest tests/unit/test_character_drift.py -v`
Expected: FAIL（`process() got an unexpected keyword argument 'drift'`）

- [ ] **Step 2: Implement minimal code**

`memory_extractor.py`のimport部（9-15行付近）に追加：

```python
from datetime import timedelta

from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT, _build_drift_section
from nous.domain.shared.time_utils import get_now
```

既存の`from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT`は上書き統合する（重複importにしない）。モジュール定数を追加：

```python
DRIFT_VALID_DAYS = 7
```

`process`署名（27-38行）に`drift`追加：

```python
    async def process(
        self,
        config: ChatConfig,
        user_message: str,
        assistant_response: str,
        *,
        context: str = "",
        commitments: str = "",
        inventory: str = "",
        persona_name: str = "assistant",
        persona_identity: str = "",
        drift: dict | None = None,
    ) -> dict:
```

prompt format部（57-66行）に1行追加：

```python
            user_message=user_message[:500],
            assistant_response=assistant_response[:500],
            drift_section=_build_drift_section(drift),
```

`run_memory_llm`の`process`呼び出し（259-268行）に1行追加：

```python
            persona_name=persona_name,
            persona_identity=persona_identity,
            drift=payload.get("drift"),
```

facts保存の`create_memory`呼び出し（287-292行）を置換：

```python
            tags = fact.get("tags", ["auto_extract"]) or ["auto_extract"]
            save_kwargs: dict = {}
            if "character_drift" in tags:
                save_kwargs["valid_until"] = get_now() + timedelta(days=DRIFT_VALID_DAYS)
            mem_result = await ctx.memory_service.create_memory(
                content=content,
                importance=float(fact.get("importance", 0.6)),
                tags=tags,
                emotion=fact.get("emotion", "neutral"),
                **save_kwargs,
            )
```

補足：`create_memory`は`**extra_fields`を`_build_memory_entity`に素通しし、`hasattr(Memory, k)`通過分だけentity化する（`write_service.py:106,131`）。`Memory`は`valid_until`を持つ（`domain/memory/entities.py:47`）ためservice層の変更は不要。

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_character_drift.py tests/unit/test_memory_llm.py -v`
Expected: PASS（新規4＋既存全pass）

- [ ] **Step 4: Commit**

```bash
git add nous/application/chat/memory_extractor.py nous/application/chat/memory_prompts.py tests/unit/test_character_drift.py
git commit -m "feat(drift): drift転送と反省文の期限付き保存"
```

---

### Task 3: post.pyでjudgmentをpayloadに載せる

**Files:**
- Modify: `nous/application/chat/pipeline/post.py:176-205`（gather部の逐次化）
- Test: `tests/unit/test_character_drift.py`（追記）

**Interfaces:**
- Consumes: Task 2の`payload["drift"]`転送。
- Produces: 違反時のみ`payload["drift"] = {"violation","detail"}`。`_with_drift(payload, judgment) -> dict`（純粋関数）。

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_drift.py`に追記：

```python
from nous.application.chat.pipeline.post import _with_drift


class TestWithDrift:
    def test_violation_attaches_drift(self):
        payload = {"user": "u", "assistant": "a"}
        out = _with_drift(payload, {"violation": "compliance", "detail": "迎合が過ぎた"})
        assert out["drift"] == {"violation": "compliance", "detail": "迎合が過ぎた"}
        assert "drift" not in payload

    def test_none_violation_returns_same(self):
        payload = {"user": "u", "assistant": "a"}
        assert _with_drift(payload, {"violation": "none", "detail": ""}) == payload
        assert _with_drift(payload, None) == payload

    def test_missing_detail_defaults_empty(self):
        out = _with_drift({"user": "u", "assistant": "a"}, {"violation": "character"})
        assert out["drift"] == {"violation": "character", "detail": ""}
```

Run: `pytest tests/unit/test_character_drift.py::TestWithDrift -v`
Expected: FAIL with "cannot import name '_with_drift'"

- [ ] **Step 2: Implement minimal code**

`post.py`のMemoryLLM並走ブロック直前（176行付近）に純粋関数を追加：

```python
def _with_drift(payload: dict, judgment: dict | None) -> dict:
    """違反判定があればpayloadにdriftを載せたコピーを返す。なければ元のまま。"""
    if judgment and judgment.get("violation") not in (None, "none"):
        return {
            **payload,
            "drift": {
                "violation": str(judgment["violation"]),
                "detail": str(judgment.get("detail", "")),
            },
        }
    return payload
```

gather部（184-205行）を逐次化に置換（judge→memoryの順。judge失敗時はwarn＋None継続で既存挙動を維持）：

```python
            if wants_judge:
                from nous.application.chat.character_judge import judge_character

                try:
                    judgment = await judge_character(config, turn_ctx.system_prompt, turn_ctx.full_response)
                except Exception as e:
                    logger.warning("PostProcessStep: judge_character failed: %s", e)
                    judgment = None
            if wants_memory:
                try:
                    memory_result = await run_memory_llm(
                        ctx, config, _with_drift(payload, judgment), tool_calls_log=turn_ctx.tool_calls_log
                    )
                except Exception as e:
                    logger.warning("PostProcessStep: run_memory_llm failed: %s", e)
```

注意：既存の`if coros:`＋`asyncio.gather`＋`results[idx]`分岐ブロックは削除する。`coros`変数も不要になる。`judgment`/`memory_result`の初期化（177-178行）は残す。

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_character_drift.py tests/unit/test_post_process_validation.py tests/unit/test_post_process_expression.py tests/unit/test_chat_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nous/application/chat/pipeline/post.py tests/unit/test_character_drift.py
git commit -m "feat(drift): judgmentをMemoryLLM payloadに載せ替え"
```

---

### Task 4: 想起の二段構え（recall除外＋直接注入）

**Files:**
- Modify: `nous/application/chat/pipeline/memory_retriever.py:9-11`（import）、`:69-75`（`_run`）
- Modify: `nous/application/chat/pipeline/context_loader.py:256-267`付近（task_stateブロック直後にdriftブロック追加）
- Test: `tests/unit/test_character_drift.py`（追記）

**Interfaces:**
- Consumes: Task 2で保存された`valid_until`付きdrift記憶。
- Produces: 期限切れdriftはrecall・直接注入の双方から除外。有効drift最新1件がcontext_section Tier3に「内面の違和感」として載る。

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_drift.py`に追記：

```python
from types import SimpleNamespace

from nous.application.chat.pipeline.context_loader import _build_context_section
from nous.application.chat.pipeline.memory_retriever import _search_memories
from nous.domain.search.engine import SearchQuery


def _make_state():
    return SimpleNamespace(
        persona="herta",
        emotion="",
        emotion_intensity=0.0,
        mental_state="",
        physical_state="",
        environment="",
        relationship_status="",
        user_info={},
        persona_info={},
    )


class TestDriftRecall:
    @pytest.mark.asyncio
    async def test_retriever_passes_valid_at(self):
        ctx = MagicMock()
        ctx.search_engine.search = AsyncMock(return_value=MagicMock(is_ok=False))
        config = MagicMock()
        config.retrieval_recency_weight = 0.3
        config.retrieval_importance_weight = 0.3
        config.retrieval_relevance_weight = 0.4
        config.retrieval_rrf_k = 5.0
        await _search_memories(ctx, "こんにちは", None, config)
        query = ctx.search_engine.search.await_args[0][0]
        assert isinstance(query, SearchQuery)
        assert query.valid_at is not None

    @pytest.mark.asyncio
    async def test_injection_includes_valid_drift(self):
        ctx = MagicMock()
        drift = SimpleNamespace(content="私は一人称を誤った", valid_until=get_now() + timedelta(days=1))
        ctx.memory_service.get_by_tags = MagicMock(return_value=Success([drift]))
        ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
        ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
        section = await _build_context_section(ctx, _make_state())
        assert "内面の違和感" in section
        assert "私は一人称を誤った" in section

    @pytest.mark.asyncio
    async def test_injection_excludes_expired_drift(self):
        ctx = MagicMock()
        drift = SimpleNamespace(content="古い反省", valid_until=get_now() - timedelta(days=1))
        ctx.memory_service.get_by_tags = MagicMock(return_value=Success([drift]))
        ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
        ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
        section = await _build_context_section(ctx, _make_state())
        assert "古い反省" not in section

    @pytest.mark.asyncio
    async def test_injection_without_drift(self):
        ctx = MagicMock()
        ctx.memory_service.get_by_tags = MagicMock(return_value=Success([]))
        ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
        ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
        section = await _build_context_section(ctx, _make_state())
        assert "内面の違和感" not in section
```

Run: `pytest tests/unit/test_character_drift.py -v`
Expected: FAIL（`SearchQuery`に`valid_at=None`、sectionに「内面の違和感」なし）

- [ ] **Step 2: Implement minimal code**

`memory_retriever.py`のimport部（9-12行付近）に追加し、`_run`内（71行）を変更：

```python
from nous.domain.shared.time_utils import get_now
```

```python
            result = await ctx.search_engine.search(SearchQuery(text=q, top_k=top_k, valid_at=get_now()))
```

`context_loader.py`のtask_stateブロック（256-267行）の直後、equipmentブロックの直前に追加（`Success`・`get_now`は既import済み：9行・260行使用）：

```python
    # Character drift — skip in light mode
    if not _is_light:
        try:
            drift_result = ctx.memory_service.get_by_tags(["character_drift"])
            if isinstance(drift_result, Success) and drift_result.value:
                now = get_now()
                valid = [
                    m
                    for m in drift_result.value
                    if m.content and (m.valid_until is None or m.valid_until > now)
                ]
                if valid:
                    latest = _sanitize_text(valid[0].content)
                    if latest:
                        t3.append("内面の違和感:\n  ⚠ " + latest)
        except Exception as e:
            logger.debug("Failed to fetch character drift: %s", e)
```

補足：`get_by_tags`の`_active_where()`はtombstone除外のみで`valid_until`を見ない（`memory_crud_repo.py:20-22`）ため、期限判定はここでPython側に行う。`get_by_tags`は`updated_at DESC`順（`memory_stats_mixin.py:87`）なので`valid[0]`が最新。

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/unit/test_character_drift.py tests/unit/test_chat_pipeline.py tests/unit/test_prompt_adherence.py tests/unit/test_prompt_relationship.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nous/application/chat/pipeline/memory_retriever.py nous/application/chat/pipeline/context_loader.py tests/unit/test_character_drift.py
git commit -m "feat(drift): 期限切れ除外と内面の違和感の直接注入"
```

---

### Task 5: 表示名統一＋全体検証

**Files:**
- Modify: `nous/api/http/static/chat/chat-core.js:553`
- Test: 既存スイート全体（回帰）

**Interfaces:**
- Consumes: Task 1-4の全変更。
- Produces: 「⚠ 内面に違和感(種別)」表示。検証済みツリー。

- [ ] **Step 1: Change the label**

`nous/api/http/static/chat/chat-core.js:553`を1行変更：

```js
badge.textContent = "⚠ 内面に違和感(" + violation + ")";
```

変更前：`badge.textContent = "⚠ キャラ逸脱: " + violation;`

- [ ] **Step 2: Verify the label and run the full gate**

Run: `Select-String -Pattern "内面に違和感" -Path nous/api/http/static/chat/chat-core.js`
Expected: 553行目に1件ヒット

Run: `pytest tests/unit/test_character_drift.py tests/unit/test_chat_pipeline.py tests/unit/test_persona_service.py tests/unit/test_post_process_validation.py tests/unit/test_prompt_adherence.py tests/unit/test_prompt_relationship.py tests/unit/test_memory_llm.py tests/unit/test_character_judge.py -v`
Expected: 失敗0

Run: `ruff check nous tests`
Expected: All checks passed

Run: `ruff format --check nous tests`
Expected: already formatted（差分があれば`ruff format`で整形して再確認）

Run: `mypy nous/application/chat/memory_extractor.py nous/application/chat/memory_prompts.py nous/application/chat/pipeline/post.py nous/application/chat/pipeline/context_loader.py nous/application/chat/pipeline/memory_retriever.py`
Expected: 新規エラー0（既存の`union-attr`・`http_client`型・`stream` override等のpre-existingのみ）

- [ ] **Step 3: Commit**

```bash
git add nous/api/http/static/chat/chat-core.js
git commit -m "feat(drift): 逸脱バッジ表示を内面に違和感へ統一"
```

---

## Self-Review

- Spec coverage: 記録（Task 1-3：反省文・tags・importance・1件・none時なし）／想起（Task 4：通常recall＋直接注入・新規スコアラなし）／減衰（Task 2のvalid_until＋Task 4の双方除外・consume-once不使用）／表示（Task 5）／テスト（記録・減衰・表示名→表示名はJS一行のためgrep検証＋SSE側は既存のまま）——spec §6の4項目すべてにtaskが紐づく。
- Placeholder scan: コードブロックはすべて実内容。TBD/TODOなし。「適宜」表現なし。
- Type consistency: `drift: dict | None`でTask 1→2→3一貫。`valid_until: datetime`（aware、`get_now()`基準）でTask 2→4一貫。`_with_drift`のdict形`{"violation","detail"}`は`_build_drift_section`の読みと一致。
