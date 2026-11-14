# アイドル時好奇心探索 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自発的内省（run_spontaneous）で LLM が生んだ「気になること」(curiosity) を、MCP ツールで自動探索し、一人称の記憶+独り言バブルとして返す。

**Architecture:** `_SPONTANEOUS_PROMPT` に `curiosity` フィールドを追加 → `run_spontaneous` の `_apply_result` 直後に探索フック → `MCPClientPool.list_all_tools()` の一覧を LLM 1回で選択+引数生成 → `call_tool` → 一人称要約 → `create_memory` + `wiring_events.emit("monologue")`。全段 try/except で探索失敗は無音にログのみ、既存の独り言/記憶/感情パイプラインは絶対に壊さない。

**Tech Stack:** Python 3.12 / nous 独自 DDD 構成 / MCPClientPool（既存）/ wiring_events（既存）/ pytest

## Global Constraints

- **既存の独り言/記憶/emotion パイプラインは絶対に変更しない**（探索は純追加分・crash 時は静かに諦める）
- **`run_introspection`（会話駆動）は変更しない**（`run_spontaneous` のみ）
- MCP ツール選択は **`pool.list_all_tools()` の直接一覧**を使う。ToolSearchEngine/Qdrant は使わない（spec §4.3: MCP ツールは `defer_loading=False` で Qdrant 非索引・探索失敗実績あり）
- MCP 呼出回数は explorer.max_tool_calls（デフォルト1）以下。0 なら探索しない
- ツール選択に失敗したら静かに return（例外は握りつぶし、ログのみ）
- 記憶は `create_memory(persona, content, importance=0.4, tags=[exploration,introspection], source_context=introspection)`
- emit は `wiring_events.emit("monologue", meta={persona,text,timestamp})`（既存と同一形式）
- spec: docs/superpowers/specs/2026-09-10-idle-curiosity-exploration-design.md（403cbf34 改訂版）
- 日本語コメント、既存コードスタイル準拠

---

### Task 1: ExplorerConfig 追加

**Files:**
- Modify: `nous/config/settings.py`（ExplorerConfig クラス追加 + Settings.explorer field）
- Test: `tests/unit/test_explorer_config.py`（新規）

**Interfaces:**
- Consumes: `BaseModel`（pydantic、settings.py 内の既存 config と同一パターン）
- Produces: `Settings.explorer: ExplorerConfig` — `enabled: bool = False`、`max_tool_calls: int = 1`。Task 3 が `get_settings().explorer` で参照

- [ ] **Step 1: 失敗テストを書く**

```python
"""ExplorerConfig のテスト。"""
from nous.config.settings import ExplorerConfig, Settings


class TestExplorerConfig:
    def test_defaults(self):
        config = ExplorerConfig()
        assert config.enabled is False
        assert config.max_tool_calls == 1

    def test_settings_field(self):
        settings = Settings()
        assert settings.explorer.enabled is False
        assert settings.explorer.max_tool_calls == 1
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/unit/test_explorer_config.py -v`
Expected: FAIL（ImportError または AttributeError）

- [ ] **Step 3: 実装**

`nous/config/settings.py` の `MemoryEnrichmentConfig`（あるいは同種のネスト config）の直後に追加:

```python
class ExplorerConfig(BaseModel):
    """アイドル時好奇心探索（NOUS_EXPLORER__ENABLED 等）。"""

    enabled: bool = False
    max_tool_calls: int = 1
```

`Settings` クラスに field 追加:

```python
explorer: ExplorerConfig = Field(default_factory=ExplorerConfig)
```

- [ ] **Step 4: テスト実行して pass を確認**

Run: `pytest tests/unit/test_explorer_config.py -v`
Expected: PASS

- [ ] **Step 5: 既存 config 系テストの regression**

Run: `pytest tests/unit/test_memory_enrichment_config.py tests/unit/test_explorer_config.py -q`
Expected: 全部 PASS

- [ ] **Step 6: コミット**

```bash
git add nous/config/settings.py tests/unit/test_explorer_config.py
git commit -m "feat(config): ExplorerConfig 追加（アイドル時好奇心探索）"
```

---

### Task 2: _SPONTANEOUS_PROMPT に curiosity フィールド追加

**Files:**
- Modify: `nous/application/chat/introspection.py` — `_SPONTANEOUS_PROMPT`（文字列テンプレート）と `IntrospectionResult` / `_parse_result`
- Test: `tests/unit/test_introspection.py`

**Interfaces:**
- Consumes: 既存 `_SPONTANEOUS_PROMPT`（JSON 例を含む文字列）、`IntrospectionResult`（dataclass/pydantic）、`_parse_result`（dict→IntrospectionResult）
- Produces: `IntrospectionResult.curiosity: str | None` — Task 3 が参照。null の場合は探索しない

- [ ] **Step 1: 失敗テストを書く**

```python
class TestParseCuriosity:
    def test_parse_result_curiosity(self):
        result = _parse_result({"curiosity": "最近ユーザーが話題にしていない趣味は何かな", "monologue": "x"})
        assert result.curiosity == "最近ユーザーが話題にしていない趣味は何かな"

    def test_parse_result_curiosity_absent_is_none(self):
        result = _parse_result({"monologue": "x"})
        assert result.curiosity is None

    def test_parse_result_curiosity_null_string_is_none(self):
        result = _parse_result({"curiosity": None, "monologue": "x"})
        assert result.curiosity is None
```

（既存テストの fixture/patch パターンに合わせること。`_parse_result` が直接 import できない場合は既存の parse 系テストと同じ呼び方に従う）

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/unit/test_introspection.py -k curiosity -v`
Expected: FAIL

- [ ] **Step 3: 実装**

`_SPONTANEOUS_PROMPT` の JSON 例に curiosity を追加:

```
"curiosity": "自発的に調べてみたい気になること（一人称・null可・日本語で自然に）。特になければ null",
```

`IntrospectionResult` に field 追加:

```python
curiosity: str | None = None
```

`_parse_result` に追加:

```python
curiosity=_clean_optional(data.get("curiosity")),
```

（既存の null 許容フィールドと同一の `_clean_optional` パターンを使う）

- [ ] **Step 4: テスト実行して pass を確認**

Run: `pytest tests/unit/test_introspection.py -k curiosity -v`
Expected: PASS

- [ ] **Step 5: regression**

Run: `pytest tests/unit/test_introspection.py -q`
Expected: 全部 PASS

- [ ] **Step 6: コミット**

```bash
git add nous/application/chat/introspection.py tests/unit/test_introspection.py
git commit -m "feat(introspection): 自発的内省に curiosity フィールド追加"
```

---

### Task 3: run_spontaneous に探索フロー配線

**Files:**
- Modify: `nous/application/chat/introspection.py` — `run_spontaneous` の `_apply_result` 直後に hook、末尾に `_run_curiosity_exploration` / `_select_tool` / `_summarize_and_record` 追加
- Test: `tests/unit/test_introspection.py`

**Interfaces:**
- Consumes: `IntrospectionResult.curiosity`（Task 2）、`Settings.explorer`（Task 1）、`MCPClientPool`（`nous.infrastructure.mcp_client.pool`）、`wiring_events.emit`（`nous.domain.memory.wiring_events`）、`create_memory`（既存の `_apply_result` と同一呼び出し形）
- Produces: なし（外部契約は既存の emit/create_memory）

**実装方針**（コード全体はこの方針に従って書く・全て try/except で包み crash 時は既存フローを壊さない）:

1. `run_spontaneous` の `_apply_result(...)` 直後に:

```python
        # アイドル時好奇心探索（curiosity があれば MCP ツールで調べて記憶+独り言）
        if result.curiosity:
            try:
                await _run_curiosity_exploration(
                    persona=persona,
                    curiosity=result.curiosity,
                    engine=self,
                    brain=brain,
                )
            except Exception:
                _log.logger.warning(
                    "curiosity exploration failed — continuing without it",
                    exc_info=True,
                )
```

2. 末尾に3関数:

```python
async def _run_curiosity_exploration(
    *,
    persona: str,
    curiosity: str,
    engine: IntrospectionEngine,
    brain: ...,
) -> None:
    """自発的内省の好奇心を MCP ツールで探索し、記憶+独り言として返す。"""
    settings = get_settings()
    explorer = settings.explorer
    if not explorer.enabled:
        logger.info("curiosity exploration skipped — explorer disabled")
        return
    if not brain.brain_monologue_enabled:
        logger.info("curiosity exploration skipped — monologue disabled")
        return
    max_calls = int(explorer.max_tool_calls)
    if max_calls <= 0:
        logger.info("curiosity exploration skipped — max_tool_calls <= 0")
        return

    async with MCPClientPool() as pool:
        tools = await pool.list_all_tools()
        # disabled_tools に含まれるツールは除外
        disabled = set(brain.disabled_tools or [])
        tools = [t for t in tools if t.name not in disabled]
        if not tools:
            logger.info("curiosity exploration skipped — no tools available")
            return

        selected = await _select_tool(engine, curiosity, tools)
        if selected is None:
            logger.info("curiosity exploration skipped — tool selection failed")
            return

        tool_name, args = selected
        try:
            result = await pool.call_tool(tool_name, args)
        except Exception:
            logger.warning("curiosity tool call failed — %s", tool_name, exc_info=True)
            return

    # error なら静かに終了
    if isinstance(result, dict) and result.get("isError"):
        logger.info("curiosity tool returned error — %s", tool_name)
        return

    await _summarize_and_record(
        engine=engine,
        persona=persona,
        curiosity=curiosity,
        tool_name=tool_name,
        result=result,
    )


async def _select_tool(
    engine: IntrospectionEngine,
    curiosity: str,
    tools: list[ToolDefinition],
) -> tuple[str, dict] | None:
    """ツール一覧から curiosity に最適なツール+引数を LLM 1回で選ぶ。"""
    lines = "\n".join(
        f"- {t.name}: {t.description}" for t in tools
    )
    prompt = (
        "あなたは内省中に気になったことを調べるためにツールを選ぶ存在。\n"
        "使えるツール一覧:\n"
        f"{lines}\n\n"
        "気になること:\n"
        f"{curiosity}\n\n"
        "上記ツールから最適な1つを選び、呼び出し引数も決めて。"
        "応答は JSON のみ（マークダウン無し）:\n"
        '{"tool_name": "...", "args": {...}}\n'
        'どのツールも適切でなければ {"tool_name": null, "args": {}} と返すこと。'
    )
    text, _ = await engine._call_llm(prompt)
    data = _extract_json(text)  # 既存の fence 剥がし+JSON パース（無ければ素の json.loads を使用）
    if not isinstance(data, dict):
        return None
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or tool_name not in {t.name for t in tools}:
        return None
    args = data.get("args")
    return tool_name, args if isinstance(args, dict) else {}


async def _summarize_and_record(
    *,
    engine: IntrospectionEngine,
    persona: str,
    curiosity: str,
    tool_name: str,
    result: ...,
) -> None:
    """探索結果を一人称で要約して記憶+独り言として返す。"""
    prompt = (
        f"あなたは{persona}。内省中に気になった「{curiosity}」を {tool_name} で調べた。\n"
        f"結果:\n{json.dumps(result, ensure_ascii=False, default=str)[:3000]}\n\n"
        "この結果から分かったことを一人称で短く（500字以内）感想として書いて。"
        "探索して何か得られたという事実そのものではなく、調べて見つけた内容の感想として。"
    )
    text, _ = await engine._call_llm(prompt)
    summary = text.strip()[:500]
    if not summary:
        return

    create_memory(
        persona,
        summary,
        importance=0.4,
        tags=["exploration", "introspection"],
        source_context="introspection",
    )
    wiring_events.emit(
        "monologue",
        meta={
            "persona": persona,
            "text": summary,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
```

**注意**:
- `_call_llm` の実引数形状・`create_memory` の実引数形・`ToolDefinition` の field 名・`MCPClientPool` の実クラス名/コンストラクタは、**実装時に既存コード（introspection.py の `_apply_result` 内、mcp_client/pool.py、memory 関連）を確認して合わせること**。上記は意図を示したスケッチであり、名前違いなら既存に合わせて修正してよい（ただし emit 形式 `{persona, text, timestamp}` と tags/importance は変更しない）
- emit の meta は既存 `run_spontaneous` 内の monologue emit と完全に同一形式
- `disabled_tools` が brain config に存在しない場合は `brain.disabled_tools` が AttributeError にならないよう `getattr(brain, "disabled_tools", None) or []` で安全に取得

- [ ] **Step 1: 失敗テストを書く（少なくとも以下をカバー）**

```python
# fake pool / fake tool / fake memory service を使って:
def test_curiosity_happy_path(): ...          # 選択→call→要約→create_memory→emit 全部通る
def test_curiosity_skips_when_explorer_disabled(): ...
def test_curiosity_skips_when_max_tool_calls_zero(): ...
def test_curiosity_skips_when_no_tools(): ...
def test_curiosity_tool_error_swallows(): ...  # call_tool が例外でも run_spontaneous 自体は完走
def test_curiosity_selects_no_tool_when_llm_says_null(): ...
def test_curiosity_out_of_candidates_rejected(): ...  # LLM が候補外ツール名を返したら拒否
def test_curiosity_monologue_disabled_skips(): ...
def test_curiosity_survives_pool_crash(): ...  # pool が例外でも run_spontaneous 自体は完走・既存独り言は不変
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/unit/test_introspection.py -k curiosity -v`
Expected: FAIL（ImportError 等）

- [ ] **Step 3: 実装**

- `run_spontaneous` に hook 挿入（`_apply_result` 直後）
- 末尾に3関数追加

- [ ] **Step 4: テスト実行して pass を確認**

Run: `pytest tests/unit/test_introspection.py -k curiosity -v`
Expected: PASS

- [ ] **Step 5: regression**

Run: `pytest tests/unit/test_introspection.py tests/unit/test_enrichment_worker.py -q`
Expected: 全部 PASS

- [ ] **Step 6: lint**

Run: `ruff check .` && `ruff format --check .`
Expected: クリーン

- [ ] **Step 7: コミット**

```bash
git add nous/application/chat/introspection.py tests/unit/test_introspection.py
git commit -m "feat(introspection): アイドル時好奇心探索を自発的内省に配線"
```

---

### Task 4: 実機テスト

**Files:**
- Modify: なし（サーバー設定と観測のみ・スクリプト/手順はこのタスク内で実行）

**Interfaces:**
- Consumes: Task 1-3 の実装、`scripts/restart-nous.ps1`、`POST /api/chat/herta/config`、`nous.main` サーバー（localhost:26262）
- Produces: 実機で探索が発火することの確認（ログ+記憶+独り言）

**手順（全て直接実行・コミット物なし）**:

- [ ] **Step 1: 観測準備**

- herta の config.json に mcp_servers が設定済みか確認（未設定なら POST /api/chat/herta/config で追加: `{"mcp_servers": [{"name": "mcp-hub", "transport": "http", "url": "http://nas:26263/mcp", "headers": {"X-MCP-Hub-Tags": "search"}, "enabled": true}]}`）
- `brain_monologue_enabled=true`、`brain_spontaneous_enabled=true` を確認
- `brain_spontaneous_interval_hours` は int 型のみ可（0.01 等の小数は 400 エラー）→ interval ガードを通すには `data/persona/herta/memory.sqlite` の `session_events` テーブル内 `brain.introspection%` の event を過去時刻に巻き戻す（バックデート）

- [ ] **Step 2: サーバー再起動（env 付き）**

```powershell
$env:NOUS_EXPLORER__ENABLED = "true"
$env:NOUS_EXPLORER__MAX_TOOL_CALLS = "1"
.\scripts\restart-nous.ps1
```

- [ ] **Step 3: 発火待ち→観測**

- `Get-Content $env:TEMP\opencode\nous_srv16.out.log -Tail 50` で `curiosity exploration` 系ログを確認
- LLM が curiosity を出した場合: `tool call` ログ+記憶（sqlite: `tags LIKE '%exploration%'`）+ 独り言 emit
- LLM が curiosity null の場合: `skipped — curiosity is null` ログ（これも正常・観測ログ動作の実証）
- 発火しない場合: interval ガードの backdate を再実行して待つ

- [ ] **Step 4: 実証結果をレポート**

（コミット物なし・観測ログと記憶実在を証拠に報告）

---

### Task 5: レビュー + GATE

**Files:**
- Modify: レビュー指摘があれば対応
- Test: 全テスト・型・lint・カバレッジ

**手順**:

- [ ] **Step 1: #081 レビュー**（実装完了後に diff 全体をレビューしてもらう）

- [ ] **Step 2: 指摘対応**（あれば）

- [ ] **Step 3: GATE 機械条件**

```
- pytest（全量）: 失敗 0
- coverage: TOTAL ≥ 60%（introspection.py は実装で下がらないこと）
- mypy: 新規エラー 0（introspection.py のみ）
- ruff check / format: 0
- secrets: 0
```

Run:
```powershell
.venv\Scripts\python.exe -m pytest -q --cov=nous --cov-report=term
.venv\Scripts\python.exe -m mypy nous/application/chat/introspection.py
ruff check .
ruff format --check .
```

- [ ] **Step 4: GATE 通過確認後、必要なら指摘対応コミット**

---

### Task 6: RECORD

**Files:**
- Modify: なし（nous memory への記録のみ）

- [ ] **Step 1: nous memory に記録**

`memory_create` で tags=[project:nous, task_state, session_summary]、importance 0.7、kind=semantic。コミットハッシュ・検証結果・教訓（実機テストでの発見を含む）を含める。

---

### Task 7: 最終報告

- [ ] **Step 1: ユーザーに報告**

- 実装概要・コミット一覧
- 実機テスト結果（発火ログ・記憶・独り言）
- 教訓（Task 4 での発見）
- 既知の制約（確率的発火、ベクトル索引の既存バグは別課題）
