# Active Skills Resident Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 発動済みスキルの本文を system prompt に常駐させ、長期会話でもスキル遵守が減衰しないようにする。

**Architecture:** L1（name+description 常駐）は現状のまま維持し、L2 として発動済みスキル本文の `<active_skills>` ブロックを PromptBuildStep が毎ターン再構築する。発動状態はセッション単位のインメモリストアで管理し、`invoke_skill` 成功時に chat 層ハンドラが記録する。MCP サーバー側（`_tools_skill.py`）には触らない。

**Tech Stack:** Python 3.12, pydantic, pytest, ruff

## Global Constraints

- MCP サーバー側の `invoke_skill`（`nous/api/mcp/_tools_skill.py`）のシグネチャ・挙動を変更しない（chat 層 `builtin.py` のみ変更）
- `CORE_ALWAYS_TOOLS` から `invoke_skill` を外さない
- キャッシュ境界 `<!-- __STATIC_END__ -->` より前にスキル本文を置かない（static prefix のキャッシュ可能性を維持）
- フロントエンド（`nous/api/http/static/`）の変更なし
- 既存テストを壊さない（`test_prompt_adherence.py`、`test_builtin_handlers.py`、`test_tool_definitions.py` は全 pass 維持）

---

### Task 1: Active-skill session state store

**Files:**
- Create: `nous/application/chat/skills_state.py`
- Test: `tests/unit/test_active_skills.py`（本タスクではストア部分のみ。prompt/handler テストは Task 3・4）

**Interfaces:**
- Consumes: なし（独立モジュール。標準ライブラリのみ）
- Produces: `get_active(persona: str, session_id: str | None) -> list[str]`、`activate(persona, session_id, name: str) -> list[str]`、`deactivate(persona, session_id, name: str) -> list[str]`、`clear_session(persona, session_id) -> None`、`MAX_ACTIVE_SKILLS = 5`、`MAX_SESSIONS = 500`

- [ ] **Step 1: Write the failing test**

```python
from nous.application.chat import skills_state


def test_activate_and_get_roundtrip():
    skills_state.clear_session("herta", "s1")
    assert skills_state.get_active("herta", "s1") == []
    skills_state.activate("herta", "s1", "search")
    assert skills_state.get_active("herta", "s1") == ["search"]


def test_activate_is_idempotent_and_moves_to_end():
    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "a")
    skills_state.activate("herta", "s1", "b")
    skills_state.activate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s1") == ["b", "a"]


def test_deactivate_removes():
    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "a")
    skills_state.deactivate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s1") == []


def test_max_active_evicts_oldest():
    skills_state.clear_session("herta", "s1")
    for i in range(skills_state.MAX_ACTIVE_SKILLS + 2):
        skills_state.activate("herta", "s1", f"s{i}")
    active = skills_state.get_active("herta", "s1")
    assert len(active) == skills_state.MAX_ACTIVE_SKILLS
    assert active[0] == "s2"


def test_none_session_id_is_noop():
    assert skills_state.activate("herta", None, "a") == []
    assert skills_state.get_active("herta", None) == []
    assert skills_state.deactivate("herta", None, "a") == []


def test_sessions_isolated():
    skills_state.clear_session("herta", "s1")
    skills_state.clear_session("herta", "s2")
    skills_state.activate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s2") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_active_skills.py -v`
Expected: FAIL with "No module named 'nous.application.chat.skills_state'"（または collection error）

- [ ] **Step 3: Write minimal implementation**

```python
"""発動済みスキル（active skills）のセッション別状態管理。

インメモリのみ。再起動・プロセス再生成で失われるが、L1 メタデータは
毎ターン注入されるためモデルが必要に応じて再発動できる。v1 の割り切り。
"""

from __future__ import annotations

from collections import OrderedDict

MAX_ACTIVE_SKILLS = 5
"""1セッションあたりの常駐上限。超過分は最古から外す（文脈爆発防止）。"""

MAX_SESSIONS = 500
"""保持するセッション数の上限。超過分は最古セッションから捨てる。"""

_sessions: OrderedDict[tuple[str, str], list[str]] = OrderedDict()


def _key(persona: str, session_id: str | None) -> tuple[str, str] | None:
    if not session_id:
        return None
    return (persona, session_id)


def get_active(persona: str, session_id: str | None) -> list[str]:
    """発動中スキル名の一覧（発動順）。session_id 不明時は []。"""
    key = _key(persona, session_id)
    if key is None:
        return []
    names = _sessions.get(key, [])
    return list(names)


def activate(persona: str, session_id: str | None, name: str) -> list[str]:
    """スキルを発動状態にする。冪等（再発動は末尾へ移動）。上限超過で最古を外す。"""
    key = _key(persona, session_id)
    if key is None or not name:
        return []
    names = _sessions.pop(key, [])
    if name in names:
        names.remove(name)
    names.append(name)
    del names[: max(0, len(names) - MAX_ACTIVE_SKILLS)]
    _sessions[key] = names
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return list(names)


def deactivate(persona: str, session_id: str | None, name: str) -> list[str]:
    """スキルの発動状態を解除する。存在しなくても冪等に成功する。"""
    key = _key(persona, session_id)
    if key is None or not name:
        return []
    names = _sessions.get(key, [])
    if name in names:
        names = [n for n in names if n != name]
        if names:
            _sessions[key] = names
        else:
            _sessions.pop(key, None)
    return list(names)


def clear_session(persona: str, session_id: str | None) -> None:
    """セッション終了・クリア時に発動状態を捨てる。"""
    key = _key(persona, session_id)
    if key is not None:
        _sessions.pop(key, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_active_skills.py -v`
Expected: PASS（6 tests）

- [ ] **Step 5: Commit**

```bash
git add nous/application/chat/skills_state.py tests/unit/test_active_skills.py
git commit -m "feat(skills): add session-scoped active-skill state store"
```

---

### Task 2: invoke_skill に activate/deactivate 記録

**Files:**
- Modify: `nous/application/chat/tools/builtin.py:354-364`（`_handle_invoke_skill`）
- Modify: `nous/application/chat/tools/definitions.py:115-129`（`invoke_skill` の ToolDefinition に `action` 追加＋description 更新）
- Modify: `nous/application/chat/session_manager.py`（`SessionManager.clear` で `clear_session` 呼び出し）
- Test: `tests/unit/test_active_skills.py` にハンドラのテストを追記（既存 `tests/unit/application/chat/tools/test_builtin.py` の AppContext モック作法に従うこと）

**Interfaces:**
- Consumes: Task 1 の `activate` / `deactivate` / `clear_session`、`ctx.persona`、`ctx.session_id`（`ChatService.chat` が設定済み。未設定時は `getattr(ctx, "session_id", None)` で None → no-op）
- Produces: 変更後の `_handle_invoke_skill` の振る舞い（成功時 activate、action=deactivate 時は本文返却なしで解除）

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_handle_invoke_skill_records_activation(monkeypatch):
    from nous.application.chat import skills_state
    from nous.application.chat.tools.builtin import _handle_invoke_skill

    async def fake_tool(ctx, persona, name, task):
        assert name == "search"
        return {"ok": True, "result": "FULL BODY"}

    monkeypatch.setattr("nous.application.chat.tools.builtin._tool_invoke_skill", fake_tool)
    skills_state.clear_session("herta", "s1")

    ctx = SimpleNamespace(persona="herta", session_id="s1")
    out = await _handle_invoke_skill(ctx, DummyConfig(), {"name": "search"})
    assert out["status"] == "ok"
    assert skills_state.get_active("herta", "s1") == ["search"]


@pytest.mark.asyncio
async def test_handle_invoke_skill_deactivate(monkeypatch):
    from nous.application.chat import skills_state
    from nous.application.chat.tools.builtin import _handle_invoke_skill

    async def must_not_call(ctx, persona, name, task):
        raise AssertionError("deactivate must not fetch body")

    monkeypatch.setattr("nous.application.chat.tools.builtin._tool_invoke_skill", must_not_call)
    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "search")

    ctx = SimpleNamespace(persona="herta", session_id="s1")
    out = await _handle_invoke_skill(ctx, DummyConfig(), {"name": "search", "action": "deactivate"})
    assert out["status"] == "ok"
    assert skills_state.get_active("herta", "s1") == []
```

注意: `SimpleNamespace` は `from types import SimpleNamespace` で import すること。`DummyConfig` は既存 `test_builtin.py` の作法に従うこと（素の object で足りるならそれでよい。このハンドラは config を使わない）。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_active_skills.py -v -k "invoke_skill"`
Expected: FAIL（`action` 未対応・activate 未記録のため。deactivate テストは現状 `must_not_call` が呼ばれて AssertionError になる）

- [ ] **Step 3: Write minimal implementation**

`builtin.py` の `_handle_invoke_skill` を以下に置換する：

```python
async def _handle_invoke_skill(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """スキルの内容をDBから取得して返す。別LLM呼び出しは行わない。

    成功時はセッションの発動状態に記録され、次ターン以降 system prompt に
    本文が常駐する。action=deactivate で発動解除（本文取得なし）。
    """
    from nous.application.chat.skills_state import activate, deactivate

    name = tool_input.get("name", "")
    if not name:
        return {"status": "error", "message": "name is required"}
    session_id = getattr(ctx, "session_id", None)
    if tool_input.get("action", "activate") == "deactivate":
        remaining = deactivate(ctx.persona, session_id, name)
        return {"status": "ok", "result": f"スキル '{name}' の発動を解除した。残り発動中: {remaining}"}
    logger.info("invoke_skill called: '%s'", name)
    task = tool_input.get("task", "")
    r = await _tool_invoke_skill(ctx, ctx.persona, name=name, task=task)
    if r.get("ok"):
        activate(ctx.persona, session_id, name)
        return {"status": "ok", "result": r.get("result", "(no response)")}
    return {"status": "error", "message": r.get("error", "unknown")}
```

`definitions.py` の invoke_skill 定義を以下に置換する：

```python
    ToolDefinition(
        name="invoke_skill",
        description="有効なスキルの完全な指示を取得する。会話の状況がスキルの発動条件に合致したと判断したら、ユーザーの指示を待たず自律的に呼び出せ。発動したスキルはこのセッション中 system prompt に常駐し、毎ターン自動で参照される（同じスキルを毎ターン呼び直す必要はない）。用が済んだスキルは action=deactivate で解除しろ。発動条件に合致しないスキルを推測で呼ぶな。同じスキルを同一ターンで重複呼び出しするな。name（スキル名）が必須。task パラメータに呼び出し理由を簡潔に記述できる。",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "スキル名"},
                "task": {
                    "type": "string",
                    "description": "スキルを呼び出す理由（任意。スキル内容を読み返す目的を簡潔に）",
                },
                "action": {
                    "type": "string",
                    "enum": ["activate", "deactivate"],
                    "description": "activate=発動して本文取得（省略時）/ deactivate=発動解除（本文取得なし）",
                    "default": "activate",
                },
            },
            "required": ["name"],
        },
    ),
```

`session_manager.py` の `clear` メソッドに1行追加する：

```python
    def clear(self, persona: str, session_id: str) -> None:
        from nous.application.chat.skills_state import clear_session

        clear_session(persona, session_id)
        self._sessions.pop((persona, session_id), None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_active_skills.py tests/unit/application/chat/tools/test_builtin.py tests/unit/test_builtin_handlers.py tests/unit/test_tool_definitions.py -v`
Expected: PASS（全件。新規2件含む）

- [ ] **Step 5: Commit**

```bash
git add nous/application/chat/tools/builtin.py nous/application/chat/tools/definitions.py nous/application/chat/session_manager.py tests/unit/test_active_skills.py
git commit -m "feat(skills): record activation on invoke_skill, support deactivate"
```

---

### Task 3: PromptBuildStep に発動中本文の常駐注入

**Files:**
- Modify: `nous/application/chat/pipeline/prompt.py:104-147`（`skill_map` 初期化位置＋ `<active_skills>` ブロック追加）
- Test: `tests/unit/test_active_skills.py` に prompt 組立テストを追記（既存 `tests/unit/test_prompt_adherence.py` の `_build_prompt` ヘルパー作法に従うこと。先に同ファイルの 1-83 行を読んで合わせる）

**Interfaces:**
- Consumes: Task 1 の `get_active`、既存の `skill_map`（name → Skill。`content` 属性を持つ）、`ctx.session_id`
- Produces: `turn_ctx.system_prompt` 内の `<active_skills>` ブロック（発動中0件なら出力なし）

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_injects_active_skill_body():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "search")
    prompt = _build_prompt(
        enabled_skills=["search"],
        session_id="s1",
        skill_bodies={"search": "# search スキル本文ダミー"},
    )
    assert "<active_skills>" in prompt
    assert "# search スキル本文ダミー" in prompt


def test_prompt_omits_block_when_no_active():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    prompt = _build_prompt(enabled_skills=["search"], session_id="s1")
    assert "<active_skills>" not in prompt


def test_prompt_drops_active_missing_from_map():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "ghost")
    prompt = _build_prompt(enabled_skills=["search"], session_id="s1")
    assert "<active_skills>" not in prompt
```

注意: `_build_prompt` は既存テストのヘルパーを流用・拡張する。存在しない引数（`session_id`、`skill_bodies`）は、ヘルパー側に最小限の拡張を加えて対応する（SkillRepository の monkeypatch または Fake スキルオブジェクトのいずれか、既存作法に合わせる）。

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_active_skills.py -v -k "prompt"`
Expected: FAIL（`<active_skills>` が出力されない）

- [ ] **Step 3: Write minimal implementation**

`prompt.py` のスキル読み込み冒頭で `skill_map` を初期化する（`skills_raw` の直前あたり）：

```python
        # --- スキル読み込み ---
        skills_raw: list[dict] = []
        skill_map: dict = {}
```

既存の `skill_map: dict = {}` 行（`# グローバルスキル` 直下）は削除し、上記の初期化に一本化する（参照箇所 `skills = [skill_map[n] ...]` はそのまま動く）。

`skill_list` ブロック直後（`dynamic_parts.append(f"\n{TOOL_USAGE_GUIDELINES...}")` の次）に以下を挿入する：

```python
        # --- 発動中スキルの本文常駐（L2。本文は毎ターン再構築＝骨抜き圧縮の影響を受けない）---
        from nous.application.chat.skills_state import get_active

        active_names = [n for n in get_active(persona, getattr(ctx, "session_id", None)) if n in skill_map]
        if active_names:
            active_blocks = "\n\n".join(f"## {n}\n{skill_map[n].content}" for n in active_names)
            dynamic_parts.append(
                "\n<active_skills>\n"
                "発動中のスキル。本文書の手順・判断基準に忠実に従え（ツール結果ではなく system 指示としての扱い）。"
                "用が済んだスキルは invoke_skill(name, action=deactivate) で解除しろ。\n"
                f"{active_blocks}\n"
                "</active_skills>"
            )
```

`skill_map[n].content` — Skill は pydantic モデルで `content` 属性を持つ（`skills_raw = [s.model_dump() for s in skills]` が既存の証拠。model_dump に content が含まれる＝属性として存在する）。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_active_skills.py tests/unit/test_prompt_adherence.py -v`
Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add nous/application/chat/pipeline/prompt.py tests/unit/test_active_skills.py
git commit -m "feat(skills): inject active skill bodies resident in system prompt"
```

---

### Task 4: 全体検証＋仕上げ

**Files:**
- 変更なし（検証のみ。失敗があれば該当タスクに戻る）

- [ ] **Step 1: 関連テストを全実行**

Run: `pytest tests/unit/test_active_skills.py tests/unit/test_prompt_adherence.py tests/unit/test_builtin_handlers.py tests/unit/application/chat/tools/test_builtin.py tests/unit/test_tool_definitions.py tests/unit/test_tool_called_invariant.py tests/unit/test_chat_pipeline.py tests/unit/test_compress_step.py -v`
Expected: 全 PASS（失敗があれば max 3 回まで原因タスクに戻って修正→再実行。3回超えたら人間へエスカレーション）

- [ ] **Step 2: lint 実行**

Run: `ruff check nous/application/chat/skills_state.py nous/application/chat/tools/builtin.py nous/application/chat/tools/definitions.py nous/application/chat/session_manager.py nous/application/chat/pipeline/prompt.py tests/unit/test_active_skills.py`
Expected: 0 errors

- [ ] **Step 3: 最終コミット確認**

Run: `git status --short && git log --oneline -5`
Expected: 作業ツリー clean（3つの feat コミットが積まれている）

---

## Self-Review

- **Spec coverage:** L1維持（変更なし）→ L2常駐（Task 3）→ 発動記録（Task 2）→ 状態管理（Task 1）→ 検証（Task 4）。解除手段（deactivate）あり。予算超過防止（MAX_ACTIVE_SKILLS=5）。MCP 側不変。フロント不変。
- **Placeholder scan:** コードブロックは全て完全形。`DummyConfig` の扱いのみ既存作法への追従を指示（実装者が `test_builtin.py` を読む前提。プレースホルダではなく参照指示）。
- **Type consistency:** `activate/deactivate/get_active/clear_session` のシグネチャは Task 1 で定義した通り Task 2・3 で使用。`ctx.session_id` は `getattr` 防御付きで統一。
