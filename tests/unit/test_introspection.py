"""内省エンジン (E2, spec §2) 単体テスト。

fetch フィルタ / JSON パース / state 適用 / 新規ターン0 skip / 反省 dedupe / monologue トグル。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.introspection import (
    IntrospectionEngine,
    fetch_recent_turns,
    run_introspection,
    run_spontaneous,
)
from nous.domain.memory import wiring_events
from nous.domain.memory.service import MemoryService
from nous.domain.persona.service import PersonaService
from nous.infrastructure.sqlite.persona_repo import SQLitePersonaRepository
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection

_CHAT_SESSIONS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS chat_sessions ("
    "persona TEXT NOT NULL, session_id TEXT NOT NULL, "
    "messages TEXT NOT NULL DEFAULT '[]', timestamps TEXT NOT NULL DEFAULT '[]', "
    "updated_at TEXT NOT NULL, PRIMARY KEY (persona, session_id))"
)

_JSON_OK = json.dumps(
    {
        "monologue": "ふふ、ちゃんと返せた。",
        "violation": "tone",
        "violation_detail": "口調が崩れた",
        "reflection": "次は口調を崩さない。",
        "emotion": {"emotion": "joy", "emotion_intensity": 0.7},
        "body_state": {"fatigue": 0.2, "warmth": 0.6, "arousal": 0.1},
    },
    ensure_ascii=False,
)


@pytest.fixture()
def ctx(sqlite_conn: SQLiteConnection):
    persona_repo = SQLitePersonaRepository(sqlite_conn)
    return SimpleNamespace(
        persona="test",
        connection=sqlite_conn,
        persona_repo=persona_repo,
        persona_service=PersonaService(persona_repo),
        memory_service=MagicMock(spec=MemoryService),
        _session_event_repo=SessionEventRepository(sqlite_conn),
    )


@pytest.fixture(autouse=True)
def _clean_wiring():
    wiring_events.clear()
    yield
    wiring_events.clear()


def _config(**overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.system_prompt = "あなたはテスト人格である。"
    cfg.brain_introspection_enabled = True
    cfg.brain_monologue_enabled = True
    for name, value in overrides.items():
        setattr(cfg, name, value)
    return cfg


def _insert_turns(db, persona: str, role_content: list[tuple[str, str]], base: datetime) -> None:
    db.execute(_CHAT_SESSIONS_SCHEMA)
    nodes = []
    prev = None
    for i, (role, content) in enumerate(role_content):
        nid = f"n{i}"
        nodes.append(
            {
                "id": nid,
                "parent_id": prev,
                "role": role,
                "content": content,
                "created_at": (base + timedelta(minutes=i)).isoformat(),
            }
        )
        prev = nid
    data = {"root_id": nodes[0]["id"] if nodes else None, "active_leaf_id": prev, "version": 0, "nodes": nodes}
    db.execute(
        "INSERT OR REPLACE INTO chat_sessions (persona, session_id, messages, timestamps, updated_at) VALUES (?,?,?,?,?)",
        (persona, "main", json.dumps(data, ensure_ascii=False), "[]", base.isoformat()),
    )


def _engine_with(result_or_none, ctx) -> MagicMock:
    engine = MagicMock()

    async def fake_generate(persona, system_prompt, recent_turns, memory_texts, current_state=None):
        assert isinstance(recent_turns, list)
        return result_or_none

    engine.generate = AsyncMock(side_effect=fake_generate)
    return engine


def _result(**overrides):
    base = dict(
        monologue="ふふ、ちゃんと返せた。",
        violation=None,
        violation_detail="",
        reflection=None,
        emotion={"emotion": "joy", "emotion_intensity": 0.7},
        body_state={"fatigue": 0.2, "warmth": 0.6, "arousal": 0.1},
    )
    base.update(overrides)
    from nous.application.chat.introspection import IntrospectionResult

    return IntrospectionResult(**base)


class TestFetchRecentTurns:
    def test_filters_since_and_roles(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(
            sqlite_conn.get_memory_db(),
            "test",
            [("user", "hi1"), ("assistant", "a1"), ("tool", "t1"), ("user", "hi2"), ("assistant", "a2")],
            base,
        )
        cutoff = base + timedelta(minutes=2, seconds=30)

        turns = fetch_recent_turns(ctx, since=cutoff)

        assert [t["role"] for t in turns] == ["user", "assistant"]
        assert turns[0]["content"] == "hi2"

    def test_caps_at_twelve_messages(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        pairs = [(role, f"c{i}") for i in range(30) for role in ("user", "assistant")]
        _insert_turns(sqlite_conn.get_memory_db(), "test", pairs, base)

        turns = fetch_recent_turns(ctx, since=None)

        assert len(turns) == 12
        assert turns[-1]["content"] == "c29"


class TestGenerate:
    def test_parses_json(self, monkeypatch) -> None:

        provider_cfg = MagicMock()
        provider_cfg.provider = "openai"
        provider_cfg.get_effective_api_key.return_value = "key"
        provider_cfg.get_effective_model.return_value = "model-x"
        provider_cfg.get_effective_base_url.return_value = "https://x/v1"
        cfg = MagicMock()
        cfg.provider_config = provider_cfg
        cfg.brain_llm_dedicated = False

        engine = IntrospectionEngine.from_config(cfg)

        assert engine is not None

        async def fake_call(user_message: str):
            return _JSON_OK, {"prompt_tokens": 10}

        monkeypatch.setattr(engine, "_call_llm", fake_call)
        result = asyncio_run_generate(engine)
        assert result is not None
        assert result.monologue == "ふふ、ちゃんと返せた。"
        assert result.violation == "tone"
        assert result.reflection == "次は口調を崩さない。"
        assert result.emotion == {"emotion": "joy", "emotion_intensity": 0.7}
        assert result.body_state == {"fatigue": 0.2, "warmth": 0.6, "arousal": 0.1}

    def test_broken_json_returns_none(self, monkeypatch) -> None:

        provider_cfg = MagicMock()
        provider_cfg.provider = "openai"
        provider_cfg.get_effective_api_key.return_value = "key"
        provider_cfg.get_effective_model.return_value = "model-x"
        provider_cfg.get_effective_base_url.return_value = "https://x/v1"
        cfg = MagicMock()
        cfg.provider_config = provider_cfg
        cfg.brain_llm_dedicated = False

        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None

        async def fake_call(user_message: str):
            return "not json at all", None

        monkeypatch.setattr(engine, "_call_llm", fake_call)
        assert asyncio_run_generate(engine) is None


def asyncio_run_generate(engine):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(
        engine.generate("test", "sp", [{"role": "user", "content": "hi"}], ["m1"])
    )


class TestReasoningBudget:
    """openrouter free alias は reasoning モデル（CoT が max_tokens を使い切る）対策。

    2026-09-08 実機: budget=512 で thinking だけ消費 → content 空 → monologue なし。
    """

    def _engine_with_stream(self, stream_fn) -> tuple[IntrospectionEngine, MagicMock]:
        provider = MagicMock()
        provider.stream = stream_fn
        return IntrospectionEngine(provider), provider

    def test_generate_requests_reasoning_safe_max_tokens(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["max_tokens"] = max_tokens
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="ok", tool_calls=[])

        engine, _ = self._engine_with_stream(stream)
        assert asyncio_run_generate(engine) is None  # "ok" は JSON でない → None
        assert captured["max_tokens"] >= 2048

    def test_engine_passes_brain_reasoning_effort_to_stream(self) -> None:
        """brain_reasoning_enabled ON → stream に effort を渡す（推論モデルは予算も増える）。"""
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["effort"] = reasoning_effort
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content='{"monologue": "ふふ、推論した。"}')
            yield DoneEvent(full_content='{"monologue": "ふふ、推論した。"}', tool_calls=[])

        engine, _ = self._engine_with_stream(stream)
        engine._reasoning_effort = "high"
        result = asyncio_run_generate(engine)
        assert captured["effort"] == "high"
        assert result is not None
        assert result.monologue == "ふふ、推論した。"

    def test_engine_default_effort_is_none(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["effort"] = reasoning_effort
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content='{"monologue": "x"}', tool_calls=[])

        engine, _ = self._engine_with_stream(stream)
        asyncio_run_generate(engine)
        assert captured["effort"] is None

    def test_from_config_resolves_brain_reasoning(self) -> None:
        provider_cfg = MagicMock()
        provider_cfg.provider = "openai"
        provider_cfg.get_effective_api_key.return_value = "key"
        provider_cfg.get_effective_model.return_value = "model-x"
        provider_cfg.get_effective_base_url.return_value = "https://x/v1"
        cfg = MagicMock()
        cfg.provider_config = provider_cfg
        cfg.brain_llm_dedicated = False
        cfg.brain_reasoning_enabled = True
        cfg.brain_reasoning_effort = "max"

        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._reasoning_effort == "max"

    def test_from_config_disabled_effort_is_none(self) -> None:
        provider_cfg = MagicMock()
        provider_cfg.provider = "openai"
        provider_cfg.get_effective_api_key.return_value = "key"
        provider_cfg.get_effective_model.return_value = "model-x"
        provider_cfg.get_effective_base_url.return_value = "https://x/v1"
        cfg = MagicMock()
        cfg.provider_config = provider_cfg
        cfg.brain_llm_dedicated = False
        cfg.brain_reasoning_enabled = False
        cfg.brain_reasoning_effort = "high"

        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._reasoning_effort is None

    def test_prompt_requires_monologue_when_turns_exist(self) -> None:
        from nous.application.chat.introspection import _INTROSPECTION_PROMPT

        assert "monologue" in _INTROSPECTION_PROMPT
        assert "必ず" in _INTROSPECTION_PROMPT

    def test_reasoning_only_stream_logs_info(self, caplog) -> None:
        """text 空でも reasoning delta があれば INFO ログで判別できること。"""
        import asyncio
        import logging

        from nous.infrastructure.llm.base import DoneEvent, ThinkingDeltaEvent

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            yield ThinkingDeltaEvent(content="thinking only")
            yield DoneEvent(full_content="", tool_calls=[])

        engine, _ = self._engine_with_stream(stream)
        # get_logger(__name__) が "nous." を二重付与する既有挙動 (nous.infrastructure.logging.structured)
        with caplog.at_level(logging.INFO, logger="nous.application.chat.introspection"):
            text, usage = asyncio.new_event_loop().run_until_complete(engine._call_llm("x"))
        assert text is None
        assert any("reasoning" in r.message for r in caplog.records if r.levelname == "INFO")


class TestParseLiteralNull:
    """モデルが JSON null でなく文字列 "null" を返すことがある（2026-09-08 プローブ実測）。

    文字列 "null" が truthy のまま通ると violation 誤検知・"null" 反省メモリ・
    "null" 独り言 emit が起きる。
    """

    def test_literal_null_strings_normalized(self) -> None:
        from nous.application.chat.introspection import _parse_result

        raw = json.dumps(
            {
                "monologue": "null",
                "violation": "null",
                "violation_detail": "null",
                "reflection": "null",
                "emotion": {"emotion": "joy", "emotion_intensity": 0.7},
                "body_state": None,
            },
            ensure_ascii=False,
        )
        r = _parse_result(raw)
        assert r is not None
        assert r.monologue is None
        assert r.violation is None
        assert r.violation_detail == ""
        assert r.reflection is None
        assert r.emotion is not None  # 実データは温存

    def test_real_monologue_survives(self) -> None:
        from nous.application.chat.introspection import _parse_result

        raw = json.dumps({"monologue": "ふふ、返せた。", "violation": None}, ensure_ascii=False)
        r = _parse_result(raw)
        assert r is not None
        assert r.monologue == "ふふ、返せた。"


class TestRunIntrospection:
    def test_applies_state_and_records(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "こんにちは"), ("assistant", "どうぞ")], base)
        engine = _engine_with(
            _result(violation="tone", violation_detail="口調が崩れた", reflection="次は口調を崩さない。"), ctx
        )

        import asyncio

        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, ["m1"]))

        hist = ctx.persona_repo.get_emotion_history("test", limit=10)
        assert hist.is_ok
        assert any(r.context == "introspection" for r in hist.value)

        ctx.memory_service.create_memory.assert_called_once()
        kwargs = ctx.memory_service.create_memory.call_args.kwargs
        assert kwargs["content"] == "次は口調を崩さない。"
        assert kwargs["importance"] == 0.8
        assert "character_drift" in kwargs["tags"]
        assert "introspection" in kwargs["tags"]

        repo = ctx._session_event_repo
        mono = repo.get_by_persona("test", "brain.monologue", 10)
        assert len(mono) == 1
        assert mono[0].summary == "ふふ、ちゃんと返せた。"
        intro = repo.get_by_persona("test", "brain.introspection", 10)
        assert len(intro) == 1

        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "monologue"]
        assert len(fires) == 1
        assert fires[0]["meta"] == {"persona": "test", "text": "ふふ、ちゃんと返せた。"}

    def test_skips_when_no_new_turns(self, ctx) -> None:
        engine = _engine_with(_result(), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, ["m1"]))

        engine.generate.assert_not_called()
        intro = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 10)
        assert intro == []

    def test_skips_after_previous_introspection(self, ctx, sqlite_conn) -> None:
        from nous.domain.memory.session_event import SessionEvent

        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "こんにちは")], base)
        ctx._session_event_repo.insert(
            SessionEvent(
                session_id="unknown",
                persona="test",
                event_type="brain.introspection",
                summary="前回",
                timestamp=base + timedelta(hours=1),
            )
        )
        engine = _engine_with(_result(), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, ["m1"]))

        engine.generate.assert_not_called()

    def test_reflection_dedupe(self, ctx, sqlite_conn) -> None:
        from nous.domain.shared.result import Success

        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "こんにちは"), ("assistant", "どうぞ")], base)
        ctx.memory_service.get_by_tags.return_value = Success([SimpleNamespace(content="次は口調を崩さない。")])
        engine = _engine_with(_result(violation="tone", violation_detail="d", reflection="次は口調を崩さない。"), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, []))

        ctx.memory_service.create_memory.assert_not_called()

    def test_respects_monologue_toggle(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "こんにちは"), ("assistant", "どうぞ")], base)
        engine = _engine_with(_result(), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(
            run_introspection(ctx, _config(brain_monologue_enabled=False), engine, ["m1"])
        )

        mono = ctx._session_event_repo.get_by_persona("test", "brain.monologue", 10)
        assert mono == []
        assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "monologue"] == []
        # 判定・状態適用は実行される
        hist = ctx.persona_repo.get_emotion_history("test", limit=10)
        assert any(r.context == "introspection" for r in hist.value)
        intro = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 10)
        assert len(intro) == 1

    def test_disabled_config_skips(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "こんにちは")], base)
        engine = _engine_with(_result(), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(
            run_introspection(ctx, _config(brain_introspection_enabled=False), engine, ["m1"])
        )

        engine.generate.assert_not_called()


class TestIntrospectionObservability:
    """失敗と成功を区別できること — 2026-09-08 の「内省は成功なのに独り言ゼロ」盲点対策。"""

    def _run(self, coro):
        import asyncio

        return asyncio.new_event_loop().run_until_complete(coro)

    def _caplog_info(self, caplog):
        import logging

        return caplog.at_level(logging.INFO, logger="nous.application.chat.introspection")

    def _messages(self, caplog) -> str:
        return " ".join(r.message for r in caplog.records if r.levelname == "INFO")

    def test_success_outcome_logged(self, ctx, sqlite_conn, caplog) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1"), ("assistant", "a1")], base)
        engine = _engine_with(_result(), ctx)
        with self._caplog_info(caplog):
            self._run(run_introspection(ctx, _config(), engine, ["m1"]))
        msgs = self._messages(caplog)
        assert "applied" in msgs
        assert "monologue=yes" in msgs

    def test_monologue_suppressed_is_visible(self, ctx, sqlite_conn, caplog) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(_result(monologue=None), ctx)
        with self._caplog_info(caplog):
            self._run(run_introspection(ctx, _config(), engine, []))
        assert "monologue=no" in self._messages(caplog)

    def test_generate_none_distinguishable_from_success(self, ctx, sqlite_conn, caplog) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(None, ctx)
        with self._caplog_info(caplog):
            self._run(run_introspection(ctx, _config(), engine, []))
        msgs = self._messages(caplog)
        assert "generate returned None" in msgs
        assert "applied" not in msgs

    def test_generate_exception_logged_at_info(self, ctx, sqlite_conn, caplog) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = MagicMock()
        engine.generate = AsyncMock(side_effect=RuntimeError("boom"))
        with self._caplog_info(caplog):
            self._run(run_introspection(ctx, _config(), engine, []))
        assert "generate failed" in self._messages(caplog)


class TestBrainMaxTokens:
    def test_engine_ctor_max_tokens_reaches_stream(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["max_tokens"] = max_tokens
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider, max_tokens=4096)
        asyncio_run_generate(engine)
        assert captured["max_tokens"] == 4096

    def test_engine_default_max_tokens_2048(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["max_tokens"] = max_tokens
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        asyncio_run_generate(engine)
        assert captured["max_tokens"] == 2048

    def test_from_config_resolves_brain_max_tokens(self) -> None:
        provider_cfg = MagicMock()
        provider_cfg.provider = "openai"
        provider_cfg.get_effective_api_key.return_value = "key"
        provider_cfg.get_effective_model.return_value = "model-x"
        provider_cfg.get_effective_base_url.return_value = "https://x/v1"
        cfg = MagicMock()
        cfg.provider_config = provider_cfg
        cfg.brain_llm_dedicated = False
        cfg.brain_max_tokens = 3072

        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._max_tokens == 3072


class TestStateMaterial:
    """材料強化: 現在の感情・身体状態＋経過時間を prompt に渡す（ターン駆動モードの穴塞ぎ）。"""

    def test_turn_prompt_has_current_state_section(self) -> None:
        from nous.application.chat.introspection import _INTROSPECTION_PROMPT

        assert "【現在の状態】" in _INTROSPECTION_PROMPT
        assert "{current_state}" in _INTROSPECTION_PROMPT
        assert "現在値との変化" in _INTROSPECTION_PROMPT

    def test_generate_injects_state_into_prompt(self) -> None:
        import asyncio

        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["user_message"] = messages[0].content
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        state = {
            "emotion": "joy",
            "emotion_intensity": 0.7,
            "body_state": {"fatigue": 0.2, "warmth": 0.6},
            "elapsed": "2時間5分",
        }
        asyncio.new_event_loop().run_until_complete(
            engine.generate("test", "sp", [{"role": "user", "content": "hi"}], [], current_state=state)
        )
        msg = captured["user_message"]
        assert "感情: joy（強度 0.7）" in msg
        assert "fatigue=0.2" in msg
        assert "前回の内省から 2時間5分" in msg

    def test_generate_state_none_placeholder(self) -> None:
        import asyncio

        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["user_message"] = messages[0].content
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        asyncio.new_event_loop().run_until_complete(
            engine.generate("test", "sp", [{"role": "user", "content": "hi"}], [], current_state=None)
        )
        assert "取得できませんでした" in captured["user_message"]

    def test_run_introspection_fetches_snapshot_and_passes_state(self, ctx, sqlite_conn) -> None:
        import asyncio

        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        captured: dict = {}

        async def fake_generate(persona, system_prompt, recent_turns, memory_texts, current_state=None):
            captured["current_state"] = current_state
            return _result()

        engine = MagicMock()
        engine.generate = AsyncMock(side_effect=fake_generate)
        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, ["m1"]))
        state = captured["current_state"]
        assert state is not None
        assert state["emotion"] == "neutral"
        assert "elapsed" in state


class TestGenerateSpontaneous:
    """自発的内省エンジン: 静かな時間に記憶＋現在状態から独り言を産出。"""

    def _engine(self, captured: dict) -> IntrospectionEngine:
        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["user_message"] = messages[0].content
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content=_JSON_OK)
            yield DoneEvent(full_content=_JSON_OK, tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        return IntrospectionEngine(provider)

    def test_prompt_content_and_memories(self) -> None:
        import asyncio

        captured: dict = {}
        engine = self._engine(captured)
        result = asyncio.new_event_loop().run_until_complete(
            engine.generate_spontaneous(
                "test",
                "あなたはテスト人格である。",
                ["思い出その1", "思い出その2"],
                {"emotion": "calm", "emotion_intensity": 0.3, "body_state": None, "elapsed": "7時間"},
            )
        )
        assert result is not None
        assert result.monologue == "ふふ、ちゃんと返せた。"
        msg = captured["user_message"]
        assert "静かな時間" in msg
        assert "思い出その1" in msg
        assert "感情: calm（強度 0.3）" in msg
        assert "7時間" in msg
        assert "monologue は必ず書くこと" in msg

    def test_broken_json_returns_none(self) -> None:
        import asyncio

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="not json", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        assert asyncio.new_event_loop().run_until_complete(engine.generate_spontaneous("t", "sp", [], None)) is None


class TestRunSpontaneous:
    """自発モード実行: 記憶取得→generate→適用、イベント種別は brain.introspection_spontaneous。"""

    def _ctx_with_memories(self, ctx, memories: list[str]) -> None:
        items = [SimpleNamespace(content=m) for m in memories]
        ctx.memory_service.get_recent = MagicMock(return_value=SimpleNamespace(is_ok=True, value=items))

    def _engine(self, result_or_none, captured: dict | None = None) -> MagicMock:
        engine = MagicMock()

        async def fake_generate_spontaneous(persona, system_prompt, memory_texts, current_state=None):
            if captured is not None:
                captured["memory_texts"] = memory_texts
                captured["current_state"] = current_state
            return result_or_none

        engine.generate_spontaneous = AsyncMock(side_effect=fake_generate_spontaneous)
        return engine

    def test_applies_and_records_spontaneous_event(self, ctx) -> None:
        import asyncio

        self._ctx_with_memories(ctx, ["思い出1", "思い出2"])
        engine = self._engine(_result())
        asyncio.new_event_loop().run_until_complete(run_spontaneous(ctx, _config(), engine, idle_seconds=25200.0))

        repo = ctx._session_event_repo
        mono = repo.get_by_persona("test", "brain.monologue", 10)
        assert len(mono) == 1
        events = repo.get_by_persona("test", "brain.introspection_spontaneous", 10)
        assert len(events) == 1
        # ターン駆動の前回内省時刻を壊さない（種別分離）
        assert repo.get_by_persona("test", "brain.introspection", 10) == []
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "monologue"]
        assert len(fires) == 1

    def test_engine_receives_memories_and_state(self, ctx) -> None:
        import asyncio

        self._ctx_with_memories(ctx, ["思い出1"])
        captured: dict = {}
        engine = self._engine(_result(), captured)
        asyncio.new_event_loop().run_until_complete(run_spontaneous(ctx, _config(), engine, idle_seconds=25200.0))
        assert captured["memory_texts"] == ["思い出1"]
        assert captured["current_state"] is not None
        assert captured["current_state"]["emotion"] == "neutral"
        assert captured["current_state"]["elapsed"] == "7時間"

    def test_generate_none_still_records_event(self, ctx) -> None:
        import asyncio

        self._ctx_with_memories(ctx, [])
        engine = self._engine(None)
        asyncio.new_event_loop().run_until_complete(run_spontaneous(ctx, _config(), engine, None))
        repo = ctx._session_event_repo
        assert len(repo.get_by_persona("test", "brain.introspection_spontaneous", 10)) == 1
        assert repo.get_by_persona("test", "brain.monologue", 10) == []

    def test_disabled_config_skips(self, ctx) -> None:
        import asyncio

        engine = self._engine(_result())
        asyncio.new_event_loop().run_until_complete(
            run_spontaneous(ctx, _config(brain_spontaneous_enabled=False), engine, None)
        )
        assert not engine.generate_spontaneous.called
        assert ctx._session_event_repo.get_by_persona("test", "brain.introspection_spontaneous", 10) == []

    def test_turn_mode_not_polluted_by_spontaneous_state(self, ctx, sqlite_conn) -> None:
        """ターン駆動の前回内省時刻判定は brain.introspection のみを読む（種別分離）。"""
        import asyncio

        from nous.domain.memory.session_event import SessionEvent

        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        ctx._session_event_repo.insert(
            SessionEvent(
                session_id="unknown",
                persona="test",
                event_type="brain.introspection_spontaneous",
                summary="自発",
                timestamp=base - timedelta(minutes=5),
                metadata=None,
            )
        )
        # brain.introspection が無い（自発のみ）→ ターン駆動は last_ts=None 扱いで全ターン対象
        engine = _engine_with(_result(), ctx)

        async def fake_generate(persona, system_prompt, recent_turns, memory_texts, current_state=None):
            fake_generate.seen_turns = recent_turns
            return _result()

        engine.generate = AsyncMock(side_effect=fake_generate)
        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, []))
        assert fake_generate.seen_turns  # 自発イベントが last_ts になっていたら空になる


class TestBodyStateHistory:
    """内省経由の身体状態適用も履歴テーブルに記録されること（decay 経由との非対称解消）。"""

    def test_apply_records_body_state_history(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(_result(body_state={"fatigue": 0.3, "warmth": 0.5, "arousal": 0.4}), ctx)

        import asyncio

        asyncio.new_event_loop().run_until_complete(run_introspection(ctx, _config(), engine, ["m1"]))

        hist = ctx.persona_service.get_body_state_history("test", limit=10)
        assert hist.is_ok
        assert hist.value, "body_state_history が空のまま（内省経由の記録漏れ）"
        assert any(r.context == "introspection" for r in hist.value)
        row = next(r for r in hist.value if r.context == "introspection")
        assert row.fatigue == pytest.approx(0.3)
        assert row.arousal == pytest.approx(0.4)


class TestPromptLanguage:
    """独り言・反省・逸脱報告の言語固定（モデル言語揺れ対策）。"""

    def test_prompts_require_japanese(self) -> None:
        from nous.application.chat.introspection import _INTROSPECTION_PROMPT, _SPONTANEOUS_PROMPT

        for prompt in (_INTROSPECTION_PROMPT, _SPONTANEOUS_PROMPT):
            assert "日本語" in prompt
            assert "必ず日本語で書く" in prompt


class TestIntrospectionMemories:
    """独り言生成時に LLM が自ら記憶を作れる（memories フィールド）。"""

    def _run(self, coro):
        import asyncio

        return asyncio.new_event_loop().run_until_complete(coro)

    def test_memories_create_memory_with_introspection_tag(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(
            _result(memories=[{"content": "新しい好み", "tags": ["preference"], "importance": 0.7}]), ctx
        )
        self._run(run_introspection(ctx, _config(), engine, ["m1"]))
        kwargs = ctx.memory_service.create_memory.call_args.kwargs
        assert kwargs["content"] == "新しい好み"
        assert "introspection" in kwargs["tags"]
        assert kwargs["importance"] == 0.7
        ev = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 1)[0]
        assert ev.metadata["stored"] == 1

    def test_no_memories_no_create(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(_result(), ctx)
        self._run(run_introspection(ctx, _config(), engine, ["m1"]))
        assert not ctx.memory_service.create_memory.called

    def test_capped_at_three(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        items = [{"content": f"事実{i}", "tags": [], "importance": 0.5} for i in range(5)]
        engine = _engine_with(_result(memories=items), ctx)
        self._run(run_introspection(ctx, _config(), engine, ["m1"]))
        assert ctx.memory_service.create_memory.call_count == 3
        ev = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 1)[0]
        assert ev.metadata["stored"] == 3

    def test_create_failure_does_not_break_introspection(self, ctx, sqlite_conn) -> None:
        base = datetime.now()
        _insert_turns(sqlite_conn.get_memory_db(), "test", [("user", "u1")], base)
        engine = _engine_with(_result(memories=[{"content": "x", "tags": [], "importance": 0.5}]), ctx)
        ctx.memory_service.create_memory = AsyncMock(side_effect=Exception("boom"))
        self._run(run_introspection(ctx, _config(), engine, ["m1"]))  # raise しない
        ev = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 1)[0]
        assert ev.metadata["stored"] == 0

    def test_prompts_have_memories_guide(self) -> None:
        from nous.application.chat.introspection import _INTROSPECTION_PROMPT, _SPONTANEOUS_PROMPT

        for prompt in (_INTROSPECTION_PROMPT, _SPONTANEOUS_PROMPT):
            assert '"memories"' in prompt
            assert "最大2件" in prompt
