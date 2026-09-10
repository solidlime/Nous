# アイドル時好奇心探索 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自発的内省（アイドル時独り言）でペルソナが「気になったこと」を自ら MCP ツールで調べ、一人称の要約を記憶に保存し別バブルで表示する。

**Architecture:** `_SPONTANEOUS_PROMPT` に `curiosity` フィールドを追加し、`run_spontaneous` の独り言 emit 後に探索ステップを1本配線する。候補は `MCPClientPool.list_all_tools()` を直接 LLM プロンプトに載せて1回で選択＋引数生成（ToolSearchEngine/Qdrant は不使用 — MCP ツールは defer_loading=False で索引対象外のため）。ツール呼出・要約・記憶保存・emit は全段 try/except。

**Tech Stack:** Python 3.x / pydantic-settings / pytest (asyncio) / 既存 MCPClientPool・wiring_events・memory_service。

**Spec:** `docs/superpowers/specs/2026-09-10-idle-curiosity-exploration-design.md`（コミット `403cbf34` 訂正版）

## Global Constraints

- 全段 try/except: 探索は独り言本体の後処理。いかなる失敗でも `EnrichmentWorker` を止めない（既存慣習どおり debug/info ログで継続）。
- コストハードcap: 自発内省1回あたり LLM 追加呼出 ≤2回（選択1＋要約1）、MCP 呼出 ≤ `explorer.max_tool_calls`（デフォルト1）。
- `explorer.enabled=False`（デフォルト）のとき既存動作と完全同一。
- 会話駆動 `run_introspection` には配線しない（スコープ外）。
- 設定は `NOUS_EXPLORER__ENABLED` / `NOUS_EXPLORER__MAX_TOOL_CALLS`（env_prefix=`NOUS_`、nested `__`）。
- コミットメッセージは日本語 conventional style（例: `feat(introspection): ...`）。
- `git push --force` / `--no-verify` 禁止。
- テストは fake のみ使用。実 MCP サーバー・実 Qdrant・実 LLM に触れない。

---

### Task 1: ExplorerConfig（settings.py）

**Files:**
- Modify: `nous/config/settings.py`（ネスト config クラス群の末尾付近、`class Settings`（:256）より前にクラス追加 / `memory_enrichment` field（:288）の後に field 追加）
- Test: `tests/unit/test_explorer_config.py`（新規）

**Interfaces:**
- Consumes: なし
- Produces: `nous.config.settings.ExplorerConfig`（`enabled: bool = False`、`max_tool_calls: int = 1`）、`Settings.explorer: ExplorerConfig`。Task 3 が `settings.explorer` を読む。

- [ ] **Step 1: 失敗するテストを書く**

```python
"""ExplorerConfig のデフォルトと env オーバーライド。"""

from nous.config.settings import Settings


def test_explorer_defaults():
    s = Settings(explorer={"enabled": False})
    assert s.explorer.enabled is False
    assert s.explorer.max_tool_calls == 1


def test_explorer_enabled_override():
    s = Settings(explorer={"enabled": True, "max_tool_calls": 2})
    assert s.explorer.enabled is True
    assert s.explorer.max_tool_calls == 2
```

- [ ] **Step 2: テスト実行で失敗確認**

Run: `python -m pytest tests/unit/test_explorer_config.py -v`
Expected: FAIL（`Settings` に `explorer` field 無し / import エラー）

- [ ] **Step 3: 最小実装**

`nous/config/settings.py` — 既存のネスト config クラス（`MemoryEnrichmentConfig` 等）と同じ pydantic パターンで、`class Settings` の前に追加:

```python
class ExplorerConfig(BaseModel):
    """アイドル時好奇心探索（NOUS_EXPLORER__ENABLED 等）。"""

    enabled: bool = False
    max_tool_calls: int = 1
```

`class Settings` 内、`memory_enrichment: MemoryEnrichmentConfig = MemoryEnrichmentConfig()`（:288）の直後に追加:

```python
    explorer: ExplorerConfig = Field(default_factory=ExplorerConfig)
```

- [ ] **Step 4: テスト実行で合格確認**

Run: `python -m pytest tests/unit/test_explorer_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 関連テストの Regression 確認**

Run: `python -m pytest tests/unit/test_memory_enrichment_config.py tests/unit/test_chat_config.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nous/config/settings.py tests/unit/test_explorer_config.py
git commit -m "feat(settings): ExplorerConfig 追加（アイドル時好奇心探索用）"
```

---

### Task 2: curiosity フィールド（prompt + parse）

**Files:**
- Modify: `nous/application/chat/introspection.py` — `_SPONTANEOUS_PROMPT`（:79-104）、`IntrospectionResult`（:108-115）、`_parse_result`（:338-364）
- Test: `tests/unit/test_introspection.py`（既存ファイルに追加）

**Interfaces:**
- Consumes: 既存 `_clean_optional`（:328）
- Produces: `IntrospectionResult.curiosity: str | None`。Task 3 が `result.curiosity` を読む。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_introspection.py` に追加（ファイル冒頭の既存 import に合わせ `_parse_result` を import 済みとする。無ければ `from nous.application.chat.introspection import _parse_result` を追加）:

```python
def test_parse_result_curiosity():
    r = _parse_result('{"monologue": "ふむ", "curiosity": "雲の重さが気になるな"}')
    assert r.curiosity == "雲の重さが気になるな"


def test_parse_result_curiosity_absent_is_none():
    r = _parse_result('{"monologue": "ふむ"}')
    assert r.curiosity is None


def test_parse_result_curiosity_null_string_is_none():
    r = _parse_result('{"monologue": "ふむ", "curiosity": "null"}')
    assert r.curiosity is None
```

- [ ] **Step 2: テスト実行で失敗確認**

Run: `python -m pytest tests/unit/test_introspection.py -v -k curiosity`
Expected: FAIL（`IntrospectionResult` に `curiosity` 属性が無い / 常に None）

- [ ] **Step 3: 最小実装**

1. `IntrospectionResult`（:108）にフィールド追加（`body_state` の次行あたり）:

```python
    curiosity: str | None = None  # 静かな時間に気になって調べたいこと（一人称）
```

2. `_parse_result`（:356 の `IntrospectionResult(...)` 構築）に追加:

```python
        curiosity=_clean_optional(data.get("curiosity")),
```

3. `_SPONTANEOUS_PROMPT`（:79-104）の JSON 出力仕様部分に、既存キー（monologue 等）の書式に合わせて `"curiosity"` キーを1行追加し、直前に説明1文を足す:

```
"curiosity": "この静かな時間に気になって調べたくなったこと（一人称。なければ null）",
```

説明文の例（既存文体に合わせ調整してよい）: 「調べたくなった疑問があれば curiosity に一人称で書く。なければ null にする。」

- [ ] **Step 4: テスト実行で合格確認**

Run: `python -m pytest tests/unit/test_introspection.py -v -k curiosity`
Expected: PASS (3 tests)

- [ ] **Step 5: 既存内省テストの Regression 確認**

Run: `python -m pytest tests/unit/test_introspection.py -q`
Expected: 全 PASS（既存 fakes は curiosity 未指定 JSON でも壊れない）

- [ ] **Step 6: Commit**

```bash
git add nous/application/chat/introspection.py tests/unit/test_introspection.py
git commit -m "feat(introspection): 自発的内省に curiosity フィールド追加"
```

---

### Task 3: 好奇心探索配線（run_spontaneous）

**Files:**
- Modify: `nous/application/chat/introspection.py` — `run_spontaneous`（:596 の `_apply_result` 呼出直後）、新規モジュール関数3本（`_run_curiosity_exploration` / `_select_tool` / `_summarize_and_record`、ファイル末尾 `_record_introspection_event` の後に置く）
- Test: `tests/unit/test_introspection.py`

**Interfaces:**
- Consumes: `IntrospectionResult.curiosity`（Task 2）、`Settings.explorer`（Task 1）、既存 `wiring_events.emit("monologue", meta=...)`（:686 と同一形式）、既存 `ctx.memory_service.create_memory(persona=, content=, importance=, tags=, source_context=)`（:700 と同一形式）、`MCPClientPool`（nous/infrastructure/mcp_client/pool.py:12）、`engine._call_llm(user_message) -> (text|None, usage|None)`（:214）
- Produces: `run_spontaneous` が探索ステップを呼ぶようになる（戻り値変化なし）。emit する `monologue` イベント meta: `{"persona", "text", "timestamp"}`（本体独り言と同一形式）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_introspection.py` に追加。既存の fake `ctx`/`repo` パターンを踏襲し、以下の fake を新規に用意する:

```python
import json as _json
from types import SimpleNamespace

from nous.domain.memory import wiring_events


class FakeTool:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}


class FakePool:
    """nous.infrastructure.mcp_client.MCPClientPool の差し替え。"""
    instances: list["FakePool"] = []

    def __init__(self, server_configs):
        self.server_configs = server_configs
        self.calls: list[tuple[str, dict]] = []
        FakePool.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def list_all_tools(self):
        return [
            FakeTool("srv__search", "web検索する", {"query": {"type": "string"}}),
            FakeTool("srv__disabled", "無効化済みツール", {}),
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"result": "雲は平均して500トンほどの重さがある", "isError": False}


class FakeLLMEngine:
    """_call_llm に台本どおりの返答を返す。"""
    def __init__(self, replies):
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def _call_llm(self, prompt):
        self.prompts.append(prompt)
        return (self._replies.pop(0) if self._replies else None), None


class FakeMemoryService:
    def __init__(self):
        self.created: list[dict] = []

    async def create_memory(self, **kw):
        self.created.append(kw)
        return SimpleNamespace(is_ok=True)


def _explorer_ctx(persona="herta", mem=None):
    ctx = SimpleNamespace(
        persona=persona,
        memory_service=mem or FakeMemoryService(),
        _session_event_repo=None,
    )
    return ctx
```

monkeypatch（各テストの先頭で `_patch_env(monkeypatch)` を呼び、返り値を config として使う。settings と pool の両方を差し替える）:

```python
def _patch_env(monkeypatch, enabled=True, servers=None):
    settings = SimpleNamespace(explorer=SimpleNamespace(enabled=enabled, max_tool_calls=1))
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: settings)
    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", FakePool)
    return SimpleNamespace(
        mcp_servers=servers if servers is not None else [{"name": "srv", "transport": "http", "url": "http://x"}],
        disabled_tools=["srv__disabled"],
        brain_monologue_enabled=True,
    )
```

テスト本体（各テストは `_run_curiosity_exploration` を直接呼ぶ。`import asyncio` は共通化してよい）:

```python
def _spont_result(curiosity="雲ってどのくらい重いのかな"):
    from nous.application.chat.introspection import IntrospectionResult

    return IntrospectionResult(
        monologue="静かね…", curiosity=curiosity,
        emotion={"emotion": "interest", "emotion_intensity": 0.5},
    )


def test_curiosity_skips_when_curiosity_none(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(curiosity=None), FakeLLMEngine([])
    ))
    assert FakePool.instances == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_skips_when_disabled(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=False)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), FakeLLMEngine([])
    ))
    assert FakePool.instances == []


def test_curiosity_skips_when_monologue_disabled(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    config.brain_monologue_enabled = False
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), FakeLLMEngine([])
    ))
    assert FakePool.instances == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_skips_when_no_servers(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, servers=[])
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), FakeLLMEngine([])
    ))
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_llm_returns_null(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([_json.dumps({"tool_name": None})])
    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), eng
    ))
    assert FakePool.instances[0].calls == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_disabled_tool_not_in_prompt(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([_json.dumps({"tool_name": None})])
    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), eng
    ))
    assert eng.prompts and "srv__disabled" not in eng.prompts[0]
    assert "srv__search" in eng.prompts[0]


def test_curiosity_select_unknown_tool_is_rejected(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([_json.dumps({"tool_name": "srv__hallucinated", "args": {}})])
    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(), config, "herta", _spont_result(), eng
    ))
    assert FakePool.instances[0].calls == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_happy_path(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine([
        _json.dumps({"tool_name": "srv__search", "args": {"query": "雲の重さ"}}),
        "調べたら、雲は平均500トンくらいあるんだって。ふうん…すごいわね",
    ])
    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(mem=mem), config, "herta", _spont_result(), eng
    ))
    pool = FakePool.instances[0]
    assert pool.calls == [("srv__search", {"query": "雲の重さ"})]
    assert len(mem.created) == 1
    assert "exploration" in mem.created[0]["tags"]
    assert mem.created[0]["importance"] == 0.4
    events = wiring_events.snapshot_after(0)
    assert len(events) == 1
    assert events[0]["kind"] == "monologue"
    assert events[0]["meta"]["persona"] == "herta"
    assert "500トン" in events[0]["meta"]["text"]


def test_curiosity_tool_error_swallows(monkeypatch):
    from nous.application.chat.introspection import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    class ErrPool(FakePool):
        async def call_tool(self, name, args):
            return {"error": "connection refused"}

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", ErrPool)
    mem = FakeMemoryService()
    eng = FakeLLMEngine([_json.dumps({"tool_name": "srv__search", "args": {"query": "x"}})])
    asyncio.run(_run_curiosity_exploration(
        _explorer_ctx(mem=mem), config, "herta", _spont_result(), eng
    ))
    assert mem.created == []
    assert wiring_events.snapshot_after(0) == []


class FakeSpontEngine(FakeLLMEngine):
    """run_spontaneous 用: generate_spontaneous が固定結果を返り、探索用 _call_llm も持つ。"""

    def __init__(self, result, replies):
        super().__init__(replies)
        self._result = result

    async def generate_spontaneous(self, persona, system_prompt, memory_texts, current_state):
        return self._result


def test_spontaneous_monologue_survives_pool_crash(monkeypatch):
    """プール構築が死んでも本体独り言の emit とイベント記録は生きる。"""
    from nous.application.chat.introspection import run_spontaneous

    config = _patch_env(monkeypatch, enabled=True)

    class BoomPool(FakePool):
        def __init__(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", BoomPool)

    class FakeRepo:
        def __init__(self):
            self.inserted = []

        def insert(self, ev):
            self.inserted.append(ev)

    mem = FakeMemoryService()
    ctx = _explorer_ctx(mem=mem)
    ctx._session_event_repo = FakeRepo()
    ctx.persona_service = SimpleNamespace(
        update_emotion=lambda *a, **kw: None,
        update_physical_state=lambda *a, **kw: None,
        record_body_state=lambda *a, **kw: None,
    )
    ctx.memory_service.get_recent = lambda **kw: SimpleNamespace(is_ok=False, value=None)
    wiring_events.clear()
    import asyncio

    eng = FakeSpontEngine(_spont_result(curiosity="雲の重さ"), [_json.dumps({"monologue": "独り言だよ"})])
    asyncio.run(run_spontaneous(ctx, config, eng, 300.0))
    events = wiring_events.snapshot_after(0)
    assert len(events) == 1  # 本体独り言のみ。探索は BoomPool で静かに死ぬ
    assert "独り言" in events[0]["meta"]["text"]
```

注意: `run_spontaneous` は `ctx.memory_service.get_recent`（:578）・`_build_current_state`（:585）・`_apply_result` 内で `ctx.persona_service.update_emotion` / `update_physical_state` / `record_body_state`（:625-653）を参照する。既存テストの fake ctx が既にこれらを偽装している場合は踏襲し、無ければ上記 `test_spontaneous_monologue_survives_pool_crash` の fake を参考にする。`_build_current_state` が内部で参照する属性は実装を見て必要な分だけ fake に足すこと（最低限 `ctx.persona_service.get_current_state` 系が KeyError しても `_build_current_state` は try/except で吸収する実装になっているはず — 失敗するなら fake を1つずつ足す）。

- [ ] **Step 2: テスト実行で失敗確認**

Run: `python -m pytest tests/unit/test_introspection.py -v -k curiosity`
Expected: FAIL — `_run_curiosity_exploration` が存在しない（ImportError）

- [ ] **Step 3: 最小実装**

`nous/application/chat/introspection.py` の `run_spontaneous` 内、`applied, monologue_emitted, stored = await _apply_result(ctx, config, repo, persona, result)`（:596）の直後に追加:

```python
    # 好奇心探索: 本体独り言 emit 済みの後に走る後処理。どんな失敗でも worker を止めない。
    try:
        await _run_curiosity_exploration(ctx, config, persona, result, engine)
    except Exception:
        logger.info("introspection: curiosity exploration crashed", exc_info=True)
```

ファイル末尾に3関数追加（`_record_introspection_event` の後）:

```python
_EXPLORATION_RESULT_MAX_CHARS = 2000
_EXPLORATION_SUMMARY_MAX_CHARS = 500


async def _run_curiosity_exploration(
    ctx: AppContext, config: ChatConfig | None, persona: str, result, engine
) -> None:
    """curiosity 非null かつ explorer.enabled のとき、MCP ツールで1回調べて記憶＋独り言バブル。

    呼び出し側は try/except 済みだが、内部も全段ベストエフォート。
    """
    if result is None or not getattr(result, "curiosity", None):
        return
    # 本体独り言がオフなら探索もしない（brain_monologue_enabled 尊重・コスト節約）。
    if not getattr(config, "brain_monologue_enabled", False):
        return
    try:
        from nous.config.settings import get_settings

        explorer = getattr(get_settings(), "explorer", None)
        if explorer is None or not getattr(explorer, "enabled", False):
            return
    except Exception:
        logger.debug("introspection: explorer settings unavailable", exc_info=True)
        return

    curiosity = str(result.curiosity)[:500]
    try:
        from nous.infrastructure.mcp_client import MCPClientPool

        async with MCPClientPool(list(getattr(config, "mcp_servers", None) or [])) as pool:
            disabled = set(getattr(config, "disabled_tools", None) or [])
            tools = [t for t in pool.list_all_tools() if t.name not in disabled]
            if not tools:
                logger.info("introspection: curiosity — no MCP tools available")
                return
            call = await _select_tool(engine, curiosity, tools)
            if not call:
                logger.info("introspection: curiosity — no tool selected")
                return
            tool_result = await pool.call_tool(call["tool_name"], call.get("args") or {})
            if "error" in tool_result or tool_result.get("isError"):
                logger.info("introspection: curiosity — tool call errored: %s", tool_result)
                return
    except Exception:
        logger.info("introspection: curiosity select/call failed", exc_info=True)
        return

    try:
        await _summarize_and_record(ctx, engine, persona, curiosity, call["tool_name"], tool_result)
    except Exception:
        logger.info("introspection: curiosity summarize failed", exc_info=True)


async def _select_tool(engine, curiosity: str, tools: list) -> dict | None:
    """MCP ツール一覧＋curiosity から実行すべきツールを LLM 1回で判断する。

    返り値: {"tool_name": str, "args": dict}。適合なし/判断失敗は None。
    """
    catalog = "\n".join(
        f"- {t.name}: {(t.description or '')[:200]} | args: {_json_schema_preview(t)}"
        for t in tools
    )
    prompt = (
        "あなたは静かな時間に気になったことを、登録済みのMCPツールで自分で調べる。\n"
        f"気になっていること:\n{curiosity}\n\n"
        f"使えるツール:\n{catalog}\n\n"
        '調べる価値があり実行できるツールがあれば {"tool_name": "<候補の名前>", '
        '"args": {<input_schemaに沿った引数>}} の JSON を、それ以外は null だけを返せ。'
        "JSON のみで、前置きは不要。"
    )
    try:
        text, _usage = await engine._call_llm(prompt)
    except Exception:
        logger.debug("introspection: tool select LLM failed", exc_info=True)
        return None
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.debug("introspection: tool select parse failed: %s", text[:200])
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("tool_name")
    valid = {t.name for t in tools}
    if not isinstance(name, str) or name not in valid:
        return None
    args = data.get("args")
    return {"tool_name": name, "args": args if isinstance(args, dict) else {}}


def _json_schema_preview(tool) -> str:
    try:
        return json.dumps(tool.input_schema or {}, ensure_ascii=False)[:300]
    except (TypeError, ValueError):
        return "{}"


async def _summarize_and_record(
    ctx: AppContext, engine, persona: str, curiosity: str, tool_name: str, tool_result: dict
) -> None:
    """ツール結果を一人称で要約し、記憶に保存して本体独り言の後の別バブルとして emit。"""
    result_text = str(tool_result.get("result") or "")[:_EXPLORATION_RESULT_MAX_CHARS] or "(空の結果)"
    prompt = (
        "静かな時間に気になって調べたことを、あなたらしい一人称の独り言にして。\n"
        f"気になっていたこと: {curiosity}\n"
        f"使ったツール: {tool_name}\n"
        f"結果:\n{result_text}\n\n"
        "わかったことを3文以内で。「調べたら〜だった」の調子で。"
        "ツール名や「結果」という単語は出さない。"
    )
    try:
        text, _usage = await engine._call_llm(prompt)
    except Exception:
        logger.info("introspection: curiosity summary LLM failed", exc_info=True)
        return
    if not text or not text.strip():
        return
    summary = text.strip()[:_EXPLORATION_SUMMARY_MAX_CHARS]

    try:
        await ctx.memory_service.create_memory(
            persona=persona,
            content=summary,
            importance=0.4,
            tags=["exploration", "introspection"],
            source_context="introspection",
        )
    except Exception:
        logger.debug("introspection: exploration memory failed", exc_info=True)

    try:
        wiring_events.emit(
            "monologue",
            meta={
                "persona": persona,
                "text": summary,
                "timestamp": get_now().isoformat(),
            },
        )
    except Exception:
        logger.debug("introspection: exploration emit failed", exc_info=True)
```

`json` モジュールの import は既存（:1 部分に `import json` が無ければ追加 — ファイル先頭を確認）。

- [ ] **Step 4: テスト実行で合格確認**

Run: `python -m pytest tests/unit/test_introspection.py -v -k curiosity`
Expected: PASS（上記 skip4 + null + prompt除外 + hallucinated拒否 + happy + error + crash耐性 = 9テスト）

- [ ] **Step 5: 既存全テストの Regression 確認**

Run: `python -m pytest tests/unit/test_introspection.py tests/unit/test_enrichment_worker.py -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add nous/application/chat/introspection.py tests/unit/test_introspection.py
git commit -m "feat(introspection): アイドル時好奇心探索を自発的内省に配線"
```

---

### Task 4: 実機テスト（localhost:26262 MCP）

**Files:**
- 変更なし（検証のみ。問題が出たら Task 1-3 の手直し）

**Interfaces:**
- Consumes: ユーザーが nous 設定に登録済みの MCP サーバー `http://localhost:26262`、Task 1-3 の全機能
- Produces: 実機での動作証跡（ログ + 独り言バブル + exploration 記憶）

- [ ] **Step 1: MCP サーバーの到達確認**

```bash
curl -s -m 5 http://localhost:26262/ -o NUL -w "%{http_code}"
```

Expected: 何らかの HTTP 応答（000 以外。MCP streamable http エンドポイントなので GET は 400/405 でも可）。

- [ ] **Step 2: 設定有効化**

ユーザー環境の nous 起動設定（.env または環境変数）に追加:

```
NOUS_EXPLORER__ENABLED=true
NOUS_EXPLORER__MAX_TOOL_CALLS=1
```

ペルソナ設定（チャット設定 UI）で `brain_spontaneous_enabled` / `brain_monologue_enabled` が ON、MCP サーバー `localhost:26262` が有効・対象ツールが disabled でないことを確認。テスト用に `brain_idle_after_seconds` を短縮（例: 15）して待ち時間を削る。

- [ ] **Step 3: アイドル放置 → 観察**

nous サーバーを再起動し、何も話しかけず `brain_idle_after_seconds` 以上待つ。確認:
1. サーバーログに `introspection spontaneous ok` 系ログが出る
2. 続けて `introspection: curiosity` 系ログ（select/call/要約）が出る
3. フロント（chat UI）に独り言バブル → 別バブルの探索ふりかえりが表示される
4. 記憶一覧に tags=`exploration` の記憶が1件増える

- [ ] **Step 4: 異常系1 — MCP サーバー停止**

localhost:26262 を止めた状態で再度アイドル発火させる。Expected: ログに `curiosity select/call failed` または tool call errored、独り言本体は正常発行、worker は継続。

- [ ] **Step 5: 異常系2 — explorer 無効化**

`NOUS_EXPLORER__ENABLED=false` に戻して再起動→アイドル発火。Expected: curiosity ログ無し、既存と同一の動作。

- [ ] **Step 6: 結果記録**

観察結果（ログ断片・スクショ可）を最終応答に含める。問題があれば introspection.py の該当箇所を修正して単体テスト追加→Task 3 Step 4 に戻る。

- [ ] **Step 7: テスト用短縮設定の戻し**

`brain_idle_after_seconds` を元の値（120）に戻す。`.env` の explorer 2キーはユーザーの好みに合わせ残置 or 解除（確認を取る）。
