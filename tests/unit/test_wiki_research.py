"""自走調査（#40）のテスト。

計画書 ``docs/superpowers/plans/2026-11-10-journal-conflicts-and-research.md`` §4.3:

- 登録 MCP サーバーが 0 件 / ツールが 0 件なら**何もしない**（プールを張らない）
- ``max_calls`` でツール呼び出しを打ち切る
- URL の取れない応答は採用しない（``## 外部情報`` に残せない）
- 接続失敗・例外は握って ``{"reason": "failed"}``（worker を落とさない・ページを変えない）
- ツールが ``isError`` を返した本文中の URL は根拠にしない
- worker 経由: research 結果は ``## 外部情報`` としてページに 1 回だけ書かれる
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nous.application.wiki import research as research_mod
from nous.application.workers import wiki_worker as wiki_worker_mod
from nous.application.workers.wiki_worker import WikiWorker
from nous.config.settings import WikiConfig
from nous.domain.memory.entities import Memory
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.base import ToolDefinition
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.wiki.store import WikiStore

_PERSONA = "test_research"
_URL_A = "https://example.com/a"
_URL_B = "https://example.com/b"


class _FakePool:
    """MCPClientPool の代役（``list_all_tools`` は sync、``call_tool`` は async）。"""

    def __init__(self, tools: list[ToolDefinition], *, fail: bool = False) -> None:
        self._tools = tools
        self.calls: list[str] = []
        self._fail = fail

    async def __aenter__(self) -> _FakePool:
        if self._fail:
            raise ConnectionError("connect refused")
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def list_all_tools(self) -> list[ToolDefinition]:
        return self._tools

    async def call_tool(self, name: str, args: dict) -> dict:
        self.calls.append(name)
        return {"result": f"{_URL_A} の内容と [解説]({_URL_B})", "isError": False}


def _tool(name: str = "mcp-hub__search") -> ToolDefinition:
    return ToolDefinition(name=name, description="検索する", input_schema={})


@pytest.fixture
def mcp_servers_env(monkeypatch):
    """登録サーバーと MCPClientPool を差し替えるヘルパを返す。"""

    def _apply(servers: list[dict], tools: list[ToolDefinition], *, fail: bool = False) -> _FakePool:
        monkeypatch.setattr(
            "nous.domain.chat_config.ChatConfigFileRepository",
            lambda _root: SimpleNamespace(get=lambda _persona: SimpleNamespace(mcp_servers=servers)),
        )
        pool = _FakePool(tools, fail=fail)
        monkeypatch.setattr("nous.infrastructure.mcp_client.pool.MCPClientPool", lambda _cfgs: pool)
        return pool

    return _apply


@pytest.fixture
def fake_steps(monkeypatch):
    """LLM の「次の一手」を固定する（呼ばれた回数も数える）。"""

    def _apply(*responses: dict) -> list[dict]:
        seen: list[dict] = []
        queue = list(responses)

        async def _ask_step(ctx, tools, question, history, *, max_calls):
            seen.append({"history": list(history)})
            return queue[min(len(seen) - 1, len(queue) - 1)] if queue else None

        monkeypatch.setattr(research_mod, "_ask_step", _ask_step)
        return seen

    return _apply


def _ctx(tmp_path, **cfg: object) -> SimpleNamespace:
    settings = SimpleNamespace(data_root=str(tmp_path), wiki=WikiConfig(**cfg))
    return SimpleNamespace(settings=settings)


# ---------------------------------------------------------------------------
# research 単体
# ---------------------------------------------------------------------------


class TestResearchModule:
    async def test_no_mcp_servers_never_opens_pool(self, tmp_path, mcp_servers_env, fake_steps) -> None:
        """登録 0 件なら MCPClientPool を張らない（LLM も呼ばない）。"""
        pool = mcp_servers_env([], [_tool()])
        steps = fake_steps({"answer": "x"})
        assert await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの") == {"reason": "no_tools"}
        assert pool.calls == []
        assert steps == []

    async def test_zero_tools_returns_empty(self, tmp_path, mcp_servers_env, fake_steps) -> None:
        """サーバーはあるがツール 0 件 → 何もしない。"""
        pool = mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp", "type": "http"}], [])
        steps = fake_steps({"answer": f"{_URL_A} の答え"})
        assert await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの") == {"reason": "no_tools"}
        assert pool.calls == []
        assert steps == []

    async def test_max_calls_caps_tool_calls(self, tmp_path, mcp_servers_env, fake_steps) -> None:
        """ツール名を返し続けても max_calls で打ち切る。"""
        pool = mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp"}], [_tool()])
        steps = fake_steps({"tool": "mcp-hub__search", "args": {"q": "blender"}})
        result = await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの", max_calls=2)
        assert pool.calls == ["mcp-hub__search", "mcp-hub__search"]
        assert len(steps) == 2
        assert result["calls"] == 2
        assert result["tools"] == ["mcp-hub__search", "mcp-hub__search"]
        assert [h["url"] for h in result["hits"]] == [_URL_B, _URL_A]

    async def test_answer_without_url_is_dropped(self, tmp_path, mcp_servers_env, fake_steps) -> None:
        """URL の無い応答は採用しない（後から検証できない）。"""
        mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp"}], [_tool()])
        fake_steps({"answer": "たぶん Blender 4.2 です。根拠はありません。"})
        # URL が取れないのは「調べたが根拠なし」。ツール不在と混ぜない。
        assert await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの") == {"reason": "no_url"}

    async def test_unknown_tool_name_is_not_executed(self, tmp_path, mcp_servers_env, fake_steps) -> None:
        """登録外のツール名（幻覚）は実行しない。"""
        pool = mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp"}], [_tool()])
        steps = fake_steps({"tool": "ddgs__search", "args": {"q": "x"}}, {"give_up": True})
        assert await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの") == {"reason": "no_url"}
        assert pool.calls == []
        assert len(steps) == 2

    async def test_connection_failure_returns_empty(self, tmp_path, mcp_servers_env) -> None:
        """接続失敗は握って理由付きで返す（例外を外に出さない）。"""
        mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp"}], [_tool()], fail=True)
        assert await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの") == {"reason": "failed"}

    async def test_broken_json_retries_once_with_bigger_budget(self, tmp_path, monkeypatch, mcp_servers_env) -> None:
        """切れ JSON は 1 回だけ予算 2 倍で再試行する（worker と同じ流儀）。"""
        mcp_servers_env([{"name": "mcp-hub", "url": "http://x/mcp"}], [_tool()])
        budgets: list[int] = []

        async def _ask(cfg, api_key, prompt, *, boost=0):
            budgets.append(research_mod._MAX_TOKENS * (2**boost))
            return '{"tool": "mcp-hub__search", ' if boost == 0 else '{"answer": "' + _URL_A + ' で確定"}'

        monkeypatch.setattr(research_mod, "_ask", _ask)
        monkeypatch.setattr(WikiConfig, "get_effective_api_key", lambda self, settings: "key")
        result = await research_mod.research(_ctx(tmp_path), _PERSONA, "調べもの")
        assert budgets == [research_mod._MAX_TOKENS, research_mod._MAX_TOKENS * 2]
        assert result["hits"] == [{"title": _URL_A, "url": _URL_A}]


# ---------------------------------------------------------------------------
# worker 経由（ページへの反映）
# ---------------------------------------------------------------------------


def _mem(key: str, *, tags: list[str] | None = None) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=f"{key} のテスト記憶内容。wiki 編纂の対象となる本文。",
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status="active",
        tags=tags or [],
    )


def _worker_setup(tmp_path, memories: list[Memory]):
    """DB + repo + ctx + worker（Qdrant は切る）。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=_PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for memory in memories:
        repo.save(memory)
    from nous.domain.memory.service import MemoryService

    settings = SimpleNamespace(data_root=str(tmp_path), wiki=WikiConfig(enabled=True))
    ctx = SimpleNamespace(
        memory_repo=repo,
        connection=conn,
        memory_service=MemoryService(repo),
        settings=settings,
    )
    worker = WikiWorker(settings)  # type: ignore[arg-type]
    worker.vector_enabled = False
    # 記憶層の掃除（#39）は別テストの担当。ここでは回さない（API key 解決を避ける）。
    worker._cfg = worker._cfg.model_copy(update={"conflict_sweep_enabled": False})
    return conn, ctx, worker


def _event_rows(conn, event_type: str) -> list[tuple[str, dict]]:
    rows = (
        conn.get_memory_db()
        .execute("SELECT summary, detail FROM session_events WHERE event_type = ? ORDER BY id", (event_type,))
        .fetchall()
    )
    return [(r["summary"], json.loads(r["detail"]) if r["detail"] else {}) for r in rows]


def _hits() -> dict:
    return {
        "answer": f"Blender 4.2 の仕様は {_URL_A} の通り",
        "calls": 1,
        "tools": ["mcp-hub__search"],
        "hits": [{"title": "Blender 4.2 Release Notes", "url": _URL_A}],
    }


class TestWorkerResearch:
    def test_research_result_is_appended_once(self, tmp_path, monkeypatch) -> None:
        """同じ slug への書込みは 1 回だけ（2 周目は本文を変えない）。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "既存本文", project="nous", sources=("k1",))
        calls: list[str] = []

        async def _research(context, persona, question, *, max_calls=3):
            calls.append(question)
            return _hits()

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        questions = [{"query": "Blender 4.2 の API は?", "topic": "project-nous-x"}]
        try:
            worker._resolve_questions(ctx, _PERSONA, store, questions)
            first = store.read_page("project-nous-x").value.body
            worker._resolve_questions(ctx, _PERSONA, store, questions)
            second = store.read_page("project-nous-x").value.body
        finally:
            conn.close()

        assert first.count("## 外部情報") == 1
        assert first.count(f"({_URL_A})") == 1
        assert first.startswith("既存本文")
        assert second == first  # 2 周目は書かない
        assert len(calls) == 2  # 調査自体は走る（結果が空でなければ）

    def test_write_event_includes_tool_calls_and_hits(self, tmp_path, monkeypatch) -> None:
        """監査: wiki.research に question / tool / calls / hits が残る。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))

        async def _research(context, persona, question, *, max_calls=3):
            return _hits()

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(ctx, _PERSONA, store, [{"query": "q", "topic": "project-nous-x"}])
            rows = _event_rows(conn, "wiki.research")
        finally:
            conn.close()

        assert len(rows) == 2  # 1 件分の調査 + 1 ページ分の書込み
        summary, detail = rows[0]
        assert "1 hits" in summary
        assert detail["tool"] == "mcp-hub__search"
        assert detail["calls"] == 1
        assert detail["hits"] == [_URL_A]
        assert rows[1][1]["slug"] == "project-nous-x"

    def test_no_mcp_tool_records_one_skip_line(self, tmp_path, monkeypatch) -> None:
        """ツールが無い日は 1 行だけ残す（ページは変えない）。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))

        async def _research(context, persona, question, *, max_calls=3):
            return {"reason": "no_tools"}

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(
                ctx, _PERSONA, store, [{"query": "a", "topic": "project-nous-x"}, {"query": "b", "topic": "x"}]
            )
            rows = _event_rows(conn, "wiki.research")
            body = store.read_page("project-nous-x").value.body
        finally:
            conn.close()

        # 実在しない slug（x）は調査前に落ちるので、skip 行も「no mcp tool」1 行だけ。
        assert [summary for summary, _ in rows][-1] == "skipped: no mcp tool"
        assert any("research target x not found" in summary for summary, _ in rows)
        assert body == "本文"

    def test_research_exception_leaves_page_untouched(self, tmp_path, monkeypatch) -> None:
        """調査が落ちても cycle は続き、ページは変わらない。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))

        async def _research(context, persona, question, *, max_calls=3):
            raise RuntimeError("mcp down")

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(ctx, _PERSONA, store, [{"query": "q", "topic": "project-nous-x"}])
            body = store.read_page("project-nous-x").value.body
            rows = _event_rows(conn, "wiki.research")
        finally:
            conn.close()

        assert body == "本文"
        # 失敗は「ツールが無い」と別の文言で残す（監査が嘘をつかない）。
        assert len(rows) == 1
        assert rows[0][0].startswith("warning: research failed for q")
        assert rows[0][1]["reason"] == "failed"

    def test_research_disabled_does_nothing(self, tmp_path, monkeypatch) -> None:
        """research_enabled=False なら research を呼ばない（監査も出さない）。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        worker._cfg = worker._cfg.model_copy(update={"research_enabled": False})
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))
        called: list[str] = []

        async def _research(context, persona, question, *, max_calls=3):
            called.append(question)
            return _hits()

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(ctx, _PERSONA, store, [{"query": "q", "topic": "project-nous-x"}])
            rows = _event_rows(conn, "wiki.research")
        finally:
            conn.close()

        assert called == []
        assert rows == []

    def test_cycle_feeds_compile_questions_into_research(self, tmp_path, monkeypatch) -> None:
        """編纂応答の questions が調査に回り、ページ末尾に根拠が載る（配線の確認）。"""
        memories = [_mem(f"k{i}", tags=["project:nous"]) for i in range(3)]
        conn, ctx, worker = _worker_setup(tmp_path, memories)
        worker._ask_llm_for_test = json.dumps(  # type: ignore[attr-defined]
            {
                "pages": [
                    {
                        "slug": "project-nous-x",
                        "title": "X",
                        "body": "本文",
                        "sources": ["k0"],
                        "delete": [],
                    }
                ],
                "conflicts": [],
                "questions": [{"query": "Blender 4.2 の API は?", "why": "根拠が無い", "topic": "project-nous-x"}],
            },
            ensure_ascii=False,
        )
        seen: list[str] = []

        async def _research(context, persona, question, *, max_calls=3):
            seen.append(question)
            return _hits()

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._compile_persona(ctx, _PERSONA)
            page = WikiStore(tmp_path, _PERSONA).read_page("project-nous-x")
            rows = _event_rows(conn, "wiki.research")
        finally:
            conn.close()

        assert seen and "Blender 4.2 の API は?" in seen[0]
        assert page.is_ok, page.error if hasattr(page, "error") else "page missing"
        body = page.value.body
        assert "## 外部情報" in body
        assert f"- [Blender 4.2 Release Notes]({_URL_A})" in body
        assert [summary for summary, _ in rows][0].startswith("research 1 hits")


class TestResearchWriteContract:
    """書込みの契約（oracle 指摘の抜けケース）。"""

    def test_two_questions_on_same_slug_write_once(self, tmp_path, monkeypatch) -> None:
        """同じ slug に 2 問落ちても write_page は 1 回だけ。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))

        async def _research(context, persona, question, *, max_calls=3):
            return {
                "answer": "ans",
                "calls": 1,
                "tools": ["mcp-hub__search"],
                "hits": [{"title": question, "url": f"{_URL_A}?q={question}"}],
            }

        written: list[str] = []
        original = store.write_page

        def _spy(slug, *args, **kwargs):
            written.append(slug)
            return original(slug, *args, **kwargs)

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        monkeypatch.setattr(store, "write_page", _spy)
        try:
            worker._resolve_questions(
                ctx,
                _PERSONA,
                store,
                [{"query": "q1", "topic": "project-nous-x"}, {"query": "q2", "topic": "project-nous-x"}],
            )
            body = store.read_page("project-nous-x").value.body
        finally:
            conn.close()

        assert written == ["project-nous-x"]
        assert "## 外部情報" in body
        assert body.count("## 外部情報") == 1

    def test_existing_section_is_not_duplicated(self, tmp_path, monkeypatch) -> None:
        """既に ``## 外部情報`` があるページは書き換えない（shortcut 経路）。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page(
            "project-nous-x",
            "X",
            "本文\n\n## 外部情報\n- [既存](https://existing.example/a)",
            project="nous",
            sources=("k1",),
        )
        before = store.read_page("project-nous-x").value

        async def _research(context, persona, question, *, max_calls=3):
            return {"answer": "a", "calls": 1, "tools": ["t"], "hits": [{"title": "n", "url": _URL_A}]}

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(ctx, _PERSONA, store, [{"query": "q", "topic": "project-nous-x"}])
            after = store.read_page("project-nous-x").value
        finally:
            conn.close()

        assert after.body == before.body
        assert after.updated == before.updated  # updated を無駄に進めない

    def test_max_research_per_cycle_caps_questions(self, tmp_path, monkeypatch) -> None:
        """``max_research_per_cycle`` を超えた問いは調査しない（LLM を焼かない）。"""
        conn, ctx, worker = _worker_setup(tmp_path, [])
        worker._cfg = worker._cfg.model_copy(update={"max_research_per_cycle": 1})
        store = WikiStore(tmp_path, _PERSONA)
        store.write_page("project-nous-x", "X", "本文", project="nous", sources=("k1",))

        asked: list[str] = []

        async def _research(context, persona, question, *, max_calls=3):
            asked.append(question)
            return {"reason": "no_tools"}

        monkeypatch.setattr(wiki_worker_mod, "research", _research)
        try:
            worker._resolve_questions(
                ctx,
                _PERSONA,
                store,
                [{"query": "q1", "topic": "project-nous-x"}, {"query": "q2", "topic": "project-nous-x"}],
            )
        finally:
            conn.close()

        assert asked == ["q1"]


async def test_tool_error_body_url_is_not_a_hit(tmp_path, mcp_servers_env, fake_steps):
    """``isError: true`` の本文に URL が混ざっても hit にしない。"""
    pool = mcp_servers_env([{"name": "hub", "url": "http://h/mcp", "type": "http"}], [_tool()])

    async def _call_tool(name: str, args: dict) -> dict:
        pool.calls.append(name)
        return {"result": f"404 Not Found: {_URL_A}", "isError": True}

    pool.call_tool = _call_tool  # type: ignore[method-assign]
    fake_steps({"tool": "mcp-hub__search", "args": {}})
    ctx = _ctx(tmp_path)

    result = await research_mod.research(ctx, _PERSONA, "q", max_calls=1)

    assert result.get("hits") is None
    assert result["reason"] == "no_url"
    assert pool.calls == ["mcp-hub__search"]


async def test_llm_no_response_is_failed_not_no_url(tmp_path, mcp_servers_env, fake_steps):
    """LLM が応答を返さないのは ``failed``（ツール未到達の ``no_url`` と混ぜない）。"""
    mcp_servers_env([{"name": "hub", "url": "http://h/mcp", "type": "http"}], [_tool()])
    fake_steps()  # queue 空 → ``_ask_step`` は None
    ctx = _ctx(tmp_path)

    result = await research_mod.research(ctx, _PERSONA, "q", max_calls=2)

    assert result == {"reason": "failed"}


@pytest.mark.parametrize(
    "payload",
    [
        {"result": f"404 Not Found: {_URL_A}", "isError": True},
        {"result": f"404 Not Found: {_URL_A}", "is_error": True},
        {"error": f"connection closed: {_URL_A}"},
    ],
)
async def test_error_shapes_never_become_hits(tmp_path, mcp_servers_env, fake_steps, payload):
    """本番で返り得る 3 つの失敗形状すべてで URL を根拠にしない。"""
    pool = mcp_servers_env([{"name": "hub", "url": "http://h/mcp", "type": "http"}], [_tool()])

    async def _call_tool(name: str, args: dict) -> dict:
        pool.calls.append(name)
        return payload

    pool.call_tool = _call_tool  # type: ignore[method-assign]
    fake_steps({"tool": "mcp-hub__search", "args": {}})
    ctx = _ctx(tmp_path)

    result = await research_mod.research(ctx, _PERSONA, "q", max_calls=1)

    assert result.get("hits") is None
    assert result["reason"] == "no_url"
