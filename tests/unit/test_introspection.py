"""内省エンジン (E2, spec §2) 単体テスト。

fetch フィルタ / JSON パース / state 適用 / 新規ターン0 skip / 反省 dedupe / monologue トグル。
"""

from __future__ import annotations

import asyncio
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

    async def fake_generate(persona, system_prompt, recent_turns, memory_texts, current_state=None, prompt_override=""):
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


class TestParseCuriosity:
    """静かな時間に気になって調べたいこと（curiosity）のパース。"""

    def test_parse_result_curiosity(self) -> None:
        from nous.application.chat.introspection import _parse_result

        r = _parse_result('{"monologue": "ふむ", "curiosity": "雲の重さが気になるな"}')
        assert r is not None
        assert r.curiosity == "雲の重さが気になるな"

    def test_parse_result_curiosity_absent_is_none(self) -> None:
        from nous.application.chat.introspection import _parse_result

        r = _parse_result('{"monologue": "ふむ"}')
        assert r is not None
        assert r.curiosity is None

    def test_parse_result_curiosity_null_string_is_none(self) -> None:
        from nous.application.chat.introspection import _parse_result

        r = _parse_result('{"monologue": "ふむ", "curiosity": "null"}')
        assert r is not None
        assert r.curiosity is None


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
        meta = fires[0]["meta"]
        assert meta["persona"] == "test"
        assert meta["text"] == "ふふ、ちゃんと返せた。"
        # ライブ配信に ISO timestamp を同梱（フロントの時系列スロット用）
        datetime.fromisoformat(meta["timestamp"])

    def test_record_event_uses_provided_timestamp(self, ctx) -> None:
        """探索前の時刻を timestamp で渡すと、その時刻で記録される（ターン喪失防止）。"""
        from nous.application.chat.introspection import _record_introspection_event

        ts = datetime.now() - timedelta(hours=1)
        _record_introspection_event(
            ctx._session_event_repo, "test", "brain.introspection", None, [], 0, 0, 0, timestamp=ts
        )
        events = ctx._session_event_repo.get_by_persona("test", "brain.introspection", 1)
        assert len(events) == 1
        assert events[0].timestamp == ts

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

    def test_engine_default_max_tokens_4096(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, reasoning_effort=None):
            captured["max_tokens"] = max_tokens
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        asyncio_run_generate(engine)
        assert captured["max_tokens"] == 4096

    def test_from_config_resolves_brain_max_tokens(self) -> None:
        """real ChatConfig 使用: 明示 brain_max_tokens が engine に渡る（新センチネル契約）。

        MagicMock cfg は brain_reasoning_enabled が truthy になり resolver の True 分岐を
        誤通過するため使わない。real ChatConfig では None（継承）/ 0（未設定）センチネルが
        正しく固定される。
        """
        from nous.domain.chat_config import ChatConfig
        from nous.domain.provider_config import ProviderConfig

        cfg = ChatConfig(
            memory_enrichment_enabled=True,
            provider_config=ProviderConfig(
                provider="openai",
                model="chat-model",
                api_key="key",
                base_url="https://x/v1",
                max_tokens=512,
            ),
            brain_max_tokens=3072,
        )
        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._max_tokens == 3072

    def test_from_config_sentinel_zero_inherits_chat(self) -> None:
        """新センチネル契約: brain_max_tokens=0（未設定）は会話側 max_tokens を継承する。"""
        from nous.domain.chat_config import ChatConfig
        from nous.domain.provider_config import ProviderConfig

        cfg = ChatConfig(
            memory_enrichment_enabled=True,
            provider_config=ProviderConfig(
                provider="openai",
                model="chat-model",
                api_key="key",
                base_url="https://x/v1",
                max_tokens=4096,
            ),
        )
        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._max_tokens == 4096  # brain_max_tokens=0 → 会話側値

    def test_from_config_off_mode_inherits_chat_params(self) -> None:
        """専用OFF + 明示なし → 会話用 provider_config の max_tokens/temperature/reasoning に従う。

        会話側 reasoning ON (high) を effort 継承するため、推論分を賄う resolver floor
        （max(8192, high budget 8192+1024) = 9216）が適用される。
        """
        from nous.domain.chat_config import ChatConfig
        from nous.domain.provider_config import ProviderConfig

        cfg = ChatConfig(
            memory_enrichment_enabled=True,
            provider_config=ProviderConfig(
                provider="openai",
                model="chat-model",
                api_key="key",
                base_url="https://x/v1",
                max_tokens=8192,
                temperature=0.9,
                reasoning_enabled=True,
                reasoning_effort="high",
            ),
        )
        engine = IntrospectionEngine.from_config(cfg)
        assert engine is not None
        assert engine._max_tokens == 9216  # reasoning high floor
        assert engine._temperature == 0.9
        assert engine._reasoning_effort == "high"


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

        async def fake_generate(
            persona, system_prompt, recent_turns, memory_texts, current_state=None, prompt_override=""
        ):
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

    def test_elapsed_label_override(self) -> None:
        """elapsed_label がある state はラベルを差し替える（spontaneous 経路: 対話なし時間）。"""
        import asyncio

        captured: dict = {}
        engine = self._engine(captured)
        state = {
            "emotion": "calm",
            "emotion_intensity": 0.3,
            "body_state": None,
            "elapsed": "7時間",
            "elapsed_label": "誰も話しかけてこない時間",
        }
        asyncio.new_event_loop().run_until_complete(engine.generate_spontaneous("test", "sp", [], state))
        assert "誰も話しかけてこない時間 7時間" in captured["user_message"]
        assert "前回の内省から" not in captured["user_message"]

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

        async def fake_generate_spontaneous(
            persona, system_prompt, memory_texts, current_state=None, prompt_override=""
        ):
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

    def test_generate_none_does_not_record_event(self, ctx) -> None:
        """失敗時は spontaneous イベントを書かずクロックを消費しない (spec A5)。"""
        import asyncio

        self._ctx_with_memories(ctx, [])
        engine = self._engine(None)
        asyncio.new_event_loop().run_until_complete(run_spontaneous(ctx, _config(), engine, None))
        repo = ctx._session_event_repo
        assert repo.get_by_persona("test", "brain.introspection_spontaneous", 10) == []
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

        async def fake_generate(
            persona, system_prompt, recent_turns, memory_texts, current_state=None, prompt_override=""
        ):
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


# --- 好奇心探索（Task 3）: アイドル時に気になったことを MCP ツールで調べる ---


class FakeTool:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}


class FakePool:
    """nous.infrastructure.mcp_client.MCPClientPool の差し替え。"""

    instances: list[FakePool] = []

    def __init__(self, server_configs):
        self.server_configs = server_configs
        self.calls: list[tuple[str, dict]] = []
        FakePool.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def list_all_tools(self):
        if not self.server_configs:
            return []
        return [
            FakeTool("srv__search", "web検索する", {"query": {"type": "string"}}),
            FakeTool("srv__get_context", "文脈取得（旧 allowlist では除外していた）", {}),
            FakeTool("srv__update_context", "文脈更新（旧 allowlist では除外していた）", {}),
            FakeTool("srv__disabled", "無効化済みツール", {}),
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return {"result": "雲は平均して500トンほどの重さがある", "isError": False}


class FakeLLMEngine:
    """research_step（native FC）に台本どおりの CollectedTurn を返す。

    messages は参照のまま保持し、後から追記された tool 応答を検証できるようにする。
    _call_llm は done summary 欠落時の要約フォールバック用。
    """

    def __init__(self, turns=None, replies=None):
        self._turns = list(turns or [])
        self._replies = list(replies or [])
        self.calls: list[dict] = []
        self.messages_refs: list[list] = []
        self.prompts: list[str] = []

    async def research_step(self, messages, tools, system="", **kwargs):
        self.calls.append({"tools": tools, "system": system, "kwargs": kwargs})
        self.messages_refs.append(messages)
        return self._turns.pop(0) if self._turns else None

    async def _call_llm(self, prompt):
        self.prompts.append(prompt)
        return (self._replies.pop(0) if self._replies else None), None


def _collected(text=None, tool_calls=None):
    from nous.infrastructure.llm.text_utils import CollectedTurn

    return CollectedTurn(text, list(tool_calls or []), None, 0)


def _tool_call(name, args=None, call_id=None, n=0):
    from nous.infrastructure.llm.base import ToolCallEvent

    return ToolCallEvent(tool_name=name, tool_input=args or {}, tool_use_id=call_id or f"call_{name}_{n}")


def _unanswered_tool_ids(messages) -> list[str]:
    """assistant の tool_calls id のうち role=tool 応答が無いものを返す（400 回帰検知）。"""
    answered = {m.tool_call_id for m in messages if getattr(m, "role", None) == "tool"}
    missing: list[str] = []
    for m in messages:
        if getattr(m, "role", None) == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("id") not in answered:
                    missing.append(tc.get("id"))
    return missing


class FakeMemoryService:
    def __init__(self):
        self.created: list[dict] = []

    async def create_memory(self, **kw):
        self.created.append(kw)
        return SimpleNamespace(is_ok=True)


def _explorer_ctx(persona="herta", mem=None):
    return SimpleNamespace(
        persona=persona,
        memory_service=mem or FakeMemoryService(),
        _session_event_repo=None,
    )


def _patch_env(monkeypatch, enabled=True, servers=None, max_tool_calls=1):
    settings = SimpleNamespace(explorer=SimpleNamespace(enabled=enabled, max_tool_calls=max_tool_calls))
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: settings)
    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", FakePool)
    return SimpleNamespace(
        mcp_servers=servers if servers is not None else [{"name": "srv", "transport": "http", "url": "http://x"}],
        disabled_tools=["srv__disabled"],
        brain_monologue_enabled=True,
        brain_spontaneous_enabled=True,
    )


def _spont_result(curiosity="雲ってどのくらい重いのかな"):
    from nous.application.chat.introspection import IntrospectionResult

    return IntrospectionResult(
        monologue="静かね…",
        curiosity=curiosity,
        emotion={"emotion": "interest", "emotion_intensity": 0.5},
    )


def test_curiosity_skips_when_curiosity_none(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(
        _run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(curiosity=None), FakeLLMEngine([]))
    )
    assert FakePool.instances == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_skips_when_disabled(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=False)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), FakeLLMEngine([])))
    assert FakePool.instances == []


def test_curiosity_skips_when_max_tool_calls_zero(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=0)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine([json.dumps({"tool_name": "srv__search", "args": {"query": "x"}})])
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances == []  # プールを開かない
    assert eng.prompts == []  # 選択 LLM を呼ばない
    assert mem.created == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_skips_when_monologue_disabled(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    config.brain_monologue_enabled = False
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), FakeLLMEngine([])))
    assert FakePool.instances == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_skips_when_no_servers(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, servers=[])
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine([json.dumps({"tool_name": "srv__search", "args": {}})])
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances  # プールは開いた（cap ガードは通過）
    assert eng.prompts == []  # ツール空 → 選択 LLM を呼ばず return
    assert mem.created == []
    assert wiring_events.snapshot_after(0) == []


class TestResearchStep:
    """IntrospectionEngine.research_step（native FC）の透過とイベント回収。"""

    def test_passes_tools_system_and_params_to_stream(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            captured.update(
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                tools=tools,
            )
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content="ok")
            yield DoneEvent(full_content="ok", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider, reasoning_effort="high", max_tokens=4096)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        tools = [ToolDefinition(name="srv__search", description="d", input_schema={"type": "object"})]
        turn = asyncio.new_event_loop().run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], tools, system="SYS")
        )
        assert captured["system"] == "SYS"
        assert captured["max_tokens"] == 4096
        assert captured["reasoning_effort"] == "high"
        assert captured["temperature"] == 0.7  # ctor 既定
        assert captured["tools"] == tools
        assert turn is not None
        assert turn.text == "ok"
        assert turn.tool_calls == []

    def test_uses_engine_resolved_temperature(self) -> None:
        """curiosity 経路は config 由来の上書きを渡さず、エンジン解決済み temperature を使う。"""
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            captured["temperature"] = temperature
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider, temperature=0.55)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        asyncio.new_event_loop().run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})])
        )
        assert captured["temperature"] == 0.55

    def test_explicit_temperature_overrides_engine_default(self) -> None:
        captured: dict = {}

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            captured["temperature"] = temperature
            from nous.infrastructure.llm.base import DoneEvent

            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider, temperature=0.55)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        asyncio.new_event_loop().run_until_complete(
            engine.research_step(
                [LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})], temperature=0.2
            )
        )
        assert captured["temperature"] == 0.2

    def test_collects_tool_calls_from_stream(self) -> None:
        from nous.infrastructure.llm.base import DoneEvent, ToolCallEvent

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            yield ToolCallEvent(tool_name="srv__search", tool_input={"q": "x"}, tool_use_id="c1")
            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        turn = asyncio.new_event_loop().run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})])
        )
        assert turn is not None
        assert turn.text is None
        assert [tc.tool_use_id for tc in turn.tool_calls] == ["c1"]

    def test_error_event_returns_empty_turn(self) -> None:
        from nous.infrastructure.llm.base import ErrorEvent

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            yield ErrorEvent(message="boom")

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        turn = asyncio.new_event_loop().run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})])
        )
        assert turn is not None
        assert turn.text is None
        assert turn.tool_calls == []

    def test_collects_finish_reason_from_done(self) -> None:
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            yield TextDeltaEvent(content="途中で切れた")
            yield DoneEvent(full_content="途中で切れた", tool_calls=[], finish_reason="length")

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        turn = asyncio.new_event_loop().run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})])
        )
        assert turn is not None
        assert turn.finish_reason == "length"

    def test_forwards_override_params_to_stream(self) -> None:
        captured: dict = {}
        from nous.infrastructure.llm.base import DoneEvent

        async def stream(messages, system, temperature, max_tokens, tools=None, reasoning_effort=None):
            captured.update(temperature=temperature, max_tokens=max_tokens, reasoning_effort=reasoning_effort)
            yield DoneEvent(full_content="", tool_calls=[])

        provider = MagicMock()
        provider.stream = stream
        engine = IntrospectionEngine(provider, reasoning_effort="high", max_tokens=4096)
        from nous.infrastructure.llm.base import LLMMessage, ToolDefinition

        loop = asyncio.new_event_loop()
        # 上書き指定 → 渡した値がそのまま provider へ。
        loop.run_until_complete(
            engine.research_step(
                [LLMMessage(role="user", content="q")],
                [ToolDefinition("t", "d", {})],
                max_tokens=8192,
                temperature=0.3,
                reasoning_effort="low",
            )
        )
        assert captured == {"temperature": 0.3, "max_tokens": 8192, "reasoning_effort": "low"}
        # 未指定 → 従来どおり self._max_tokens / self._reasoning_effort。
        loop.run_until_complete(
            engine.research_step([LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})])
        )
        assert captured == {"temperature": 0.7, "max_tokens": 4096, "reasoning_effort": "high"}
        # reasoning_effort=None 明示渡し → engine 既定 ("high") ではなく None が優先。
        loop.run_until_complete(
            engine.research_step(
                [LLMMessage(role="user", content="q")], [ToolDefinition("t", "d", {})], reasoning_effort=None
            )
        )
        assert captured == {"temperature": 0.7, "max_tokens": 4096, "reasoning_effort": None}
        loop.close()


def test_curiosity_tool_calls_with_length_finish_executes_normally(monkeypatch, caplog):
    """tool_calls 非空 + finish_reason=length のターンも通常実行する（切断は openai_compat が引数JSONで棄てる）。

    length 信号は step 実行ログ (finish=) と break パスの warning で観測可能にする。
    """
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    mem = FakeMemoryService()
    turn = _collected(None, [_tool_call("srv__search", {"q": "x"})])
    # finish_reason 付きに差し替え（NamedTuple._replace）
    turn = turn._replace(finish_reason="length")
    eng = FakeLLMEngine([turn])
    import logging

    with caplog.at_level(logging.INFO, logger="nous.application.chat.introspection"):
        asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == [("srv__search", {"q": "x"})]
    assert any("finish=length" in r.message for r in caplog.records)


def test_curiosity_research_step_none_noop(monkeypatch, caplog):
    """research_step が None（LLM エラー/例外）なら no-op で静かに終わる。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio
    import logging

    eng = FakeLLMEngine([None])
    with caplog.at_level(logging.INFO, logger="nous.application.chat.introspection"):
        asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == []
    assert len(eng.calls) == 1
    assert wiring_events.snapshot_after(0) == []
    assert "no results collected" in " ".join(r.message for r in caplog.records)


def test_curiosity_fc_unsupported_noop_logs(monkeypatch, caplog):
    """FC 非対応（tool_calls が出ない台本）は無言 no-op にせず INFO ログで検知できる。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio
    import logging

    eng = FakeLLMEngine([_collected(None, [])])
    with caplog.at_level(logging.INFO, logger="nous.application.chat.introspection"):
        asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == []
    assert len(eng.calls) == 1
    assert wiring_events.snapshot_after(0) == []
    assert "no results collected" in " ".join(r.message for r in caplog.records)


def test_curiosity_tool_array_excludes_disabled(monkeypatch):
    """tools は tool 配列として渡す。disabled_tools は配列から除外。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([None])
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    names = [t.name for t in eng.calls[0]["tools"]]
    assert "srv__disabled" not in names
    assert "srv__search" in names


def test_curiosity_tool_array_excludes_get_context(monkeypatch):
    """全開放方針でも get_context だけは record_conversation_time 副作用のため除外。更新系は載る。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([None])
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    names = [t.name for t in eng.calls[0]["tools"]]
    assert "srv__get_context" not in names
    assert "srv__update_context" in names


def test_curiosity_unknown_tool_feeds_back(monkeypatch):
    """一覧外ツールは実行せず、拒否を tool 応答で返して次ステップへ進む。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__hallucinated", {"query": "x"})]),
            _collected("調べ終わった。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == []  # 実行しない
    assert len(eng.calls) == 2  # 却下後も次ステップへ進む
    # 拒否が role=tool 応答として履歴に載る（次リクエスト 400 防止）
    reject = [m for m in eng.messages_refs[1] if m.role == "tool"]
    assert reject and "存在しない" in reject[0].content
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_aborts_after_repeated_unknown_tools(monkeypatch):
    """未知ツール提案が連続2回で打ち切り、要約へ進む。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__ghost1")]),
            _collected(None, [_tool_call("srv__ghost2")]),
            _collected("x"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == []
    assert len(eng.calls) == 2  # 3 回目は break
    assert mem.created == []
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []


def test_curiosity_happy_path(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"query": "雲の重さ"})]),
            _collected("調べたら、雲は平均500トンくらいあるんだって。ふうん…すごいわね"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    pool = FakePool.instances[0]
    assert pool.calls == [("srv__search", {"query": "雲の重さ"})]
    assert len(mem.created) == 1
    assert "exploration" in mem.created[0]["tags"]
    assert mem.created[0]["importance"] == 0.4
    # assistant の tool_calls が履歴に載り、全 tool_call_id に応答が返る
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    # 🔍 bubble 生成は廃止済み — monologue emit は行わない
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_tool_error_swallows(monkeypatch):
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    class ErrPool(FakePool):
        async def call_tool(self, name, args):
            return {"error": "connection refused"}

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", ErrPool)
    mem = FakeMemoryService()
    eng = FakeLLMEngine([_collected(None, [_tool_call("srv__search", {"query": "x"})])])
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert mem.created == []
    assert wiring_events.snapshot_after(0) == []
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []


def test_curiosity_aborts_after_two_consecutive_errors(monkeypatch):
    """連続エラー2回で打ち切り、要約へ進む（無制限リトライしない）。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    error_calls: list[tuple] = []

    class ErrPool(FakePool):
        async def call_tool(self, name, args):
            error_calls.append((name, args))
            return {"error": "boom"}

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", ErrPool)
    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected(None, [_tool_call("srv__search", {"q": "2"})]),
        ],
        replies=[
            json.dumps({"summary": "失敗続きだった。", "satisfied": False, "unresolved": None}, ensure_ascii=False)
        ],
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert len(error_calls) == 2  # 3 回目は実行しない
    # 空振り (satisfied=False) は要約記憶も bubble も何も残さない。
    assert len(mem.created) == 0
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []


def test_curiosity_multi_step_until_done(monkeypatch):
    """多段: 2 ステップのツール実行 → 最終回答で抜ける。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"query": "雲の重さ"})]),
            _collected(None, [_tool_call("srv__search", {"query": "雲のできる仕組み"})]),
            _collected("雲は500トンで、でき方もわかった。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    pool = FakePool.instances[0]
    assert [c[0] for c in pool.calls] == ["srv__search", "srv__search"]
    assert len(pool.calls) == 2
    assert len(eng.calls) == 3
    assert len(mem.created) == 1
    assert "500トン" in mem.created[0]["content"]
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    # 🔍 bubble 生成は廃止済み — monologue emit は行わない
    assert len(wiring_events.snapshot_after(0)) == 0


def test_curiosity_budget_exhaustion_stops_at_max(monkeypatch):
    """最終回答が無くても予算 max_tool_calls で打ち切り、要約へフォールバックする。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=2)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected(None, [_tool_call("srv__search", {"q": "2"})]),
        ],
        replies=[json.dumps({"summary": "2段調べた。", "satisfied": True, "unresolved": None}, ensure_ascii=False)],
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert len(FakePool.instances[0].calls) == 2
    assert len(eng.calls) == 2
    assert len(mem.created) == 1
    assert len(eng.prompts) == 1  # done が無いので要約 LLM 1回（フォールバック）


class FakeResumeRepo:
    """last_activity_at の返値を呼び出し回数で切り替える偽リポジトリ（チャット再検知テスト用）。

    最初の switch_after 回は before を返し（= baseline 取得＋最初のループチェック）、
    以降は after を返す（= チャット再開を検知させる）。before == after なら再開なし。
    """

    def __init__(self, before, after, switch_after=2):
        self.before = before
        self.after = after
        self.switch_after = switch_after
        self.calls = 0

    def last_activity_at(self, persona):
        self.calls += 1
        return self.before if self.calls <= self.switch_after else self.after


def test_curiosity_aborts_when_chat_resumed(monkeypatch, caplog):
    """探索中にチャット再開（chat イベントが baseline より新しくなった）したら打ち切り。

    2ステップ目の research_step を呼ばず、要約・記憶・emit も行わない。
    """
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import logging

    base = datetime(2026, 1, 1, 12, 0, 0)
    repo = FakeResumeRepo(before=base, after=base + timedelta(minutes=5))
    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected(None, [_tool_call("srv__search", {"q": "2"})]),
        ]
    )
    c = _explorer_ctx(mem=mem)
    c._session_event_repo = repo
    with caplog.at_level(logging.INFO, logger="nous.application.chat.introspection"):
        asyncio.run(_run_curiosity_exploration(c, config, "herta", _spont_result(), eng))
    assert len(eng.calls) == 1  # 2ステップ目の research_step は呼ばない
    assert "chat resumed" in " ".join(r.message for r in caplog.records)
    assert mem.created == []  # 要約・記憶保存をスキップ
    assert wiring_events.snapshot_after(0) == []  # emit もしない
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []  # 未応答 tool_call_id を残さない


def test_curiosity_chat_not_resumed_completes(monkeypatch):
    """chat イベントが baseline から動かなければ従来どおり完走（要約・emit まで進む）。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()

    base = datetime(2026, 1, 1, 12, 0, 0)
    repo = FakeResumeRepo(before=base, after=base)  # 常に同じ時刻 = 再開なし
    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected("調べたら、雲は500トンくらいあるんだって。"),
        ]
    )
    c = _explorer_ctx(mem=mem)
    c._session_event_repo = repo
    asyncio.run(_run_curiosity_exploration(c, config, "herta", _spont_result(), eng))
    assert len(eng.calls) == 2  # 打ち切りされず完走
    assert len(mem.created) == 1
    assert len(wiring_events.snapshot_after(0)) == 0  # bubble 廃止済み


def test_curiosity_done_summary_skips_summary_llm(monkeypatch):
    """最終回答テキストを同梱したら要約 LLM を呼ばず、その summary で記憶・emit する。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected("調べたら、雲は500トンくらいあるんだって。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert len(eng.calls) == 2  # 判断2回のみ。要約 LLM はスキップ
    assert eng.prompts == []
    assert len(mem.created) == 1
    assert "500トン" in mem.created[0]["content"]
    # 🔍 bubble 生成は廃止済み — monologue emit は行わない
    assert wiring_events.snapshot_after(0) == []


def test_curiosity_done_without_summary_falls_back(monkeypatch):
    """最終回答テキストが無ければ従来どおり要約 LLM 呼び出しにフォールバックする。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected(None, []),
        ],
        replies=[
            json.dumps({"summary": "調べたら分かった。", "satisfied": True, "unresolved": None}, ensure_ascii=False)
        ],
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert len(eng.calls) == 2  # 判断2回
    assert len(eng.prompts) == 1  # 要約 LLM 1回
    assert len(mem.created) == 1


def test_curiosity_passes_all_results_to_summarize(monkeypatch):
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    captured: dict = {}

    async def fake_summarize(ctx, engine, persona, curiosity, results, summary=None):
        captured["results"] = results

    from nous.application.chat import curiosity as _curiosity_mod

    monkeypatch.setattr(_curiosity_mod, "_summarize_and_record", fake_summarize)
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected(None, [_tool_call("srv__search", {"q": "2"})]),
            _collected("調べ終わった。"),
        ]
    )
    asyncio.run(mod._run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    assert [r["tool_name"] for r in captured["results"]] == ["srv__search", "srv__search"]
    assert all("result" in r for r in captured["results"])


def test_curiosity_execute_tool_get_context_rejected(monkeypatch):
    """hub の execute_tool(args.tool_name=get_context) 経由の get_context 迂回を拒否する。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    class HubPool(FakePool):
        def list_all_tools(self):
            return [FakeTool("srv__execute_tool", "hub 実行", {"tool_name": {"type": "string"}})]

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", HubPool)
    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            # get_context への迂回 → 拒否
            _collected(
                None,
                [
                    _tool_call(
                        "srv__execute_tool",
                        {"server": "nous", "tool_name": "get_context", "arguments": {}},
                        n=1,
                    )
                ],
            ),
            # 別 inner ツール → 通過して実行
            _collected(
                None,
                [
                    _tool_call(
                        "srv__execute_tool",
                        {"server": "nous", "tool_name": "memory_search", "arguments": {}},
                        n=2,
                    )
                ],
            ),
            _collected("調べた。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    pool = FakePool.instances[0]
    # get_context は実行されず、memory_search のみ実行される
    assert len(pool.calls) == 1
    assert pool.calls[0][1]["tool_name"] == "memory_search"
    # 拒否が tool 応答として履歴に載る
    rejects = [m for m in eng.messages_refs[-1] if m.role == "tool" and "get_context" in (m.content or "")]
    assert rejects
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    assert len(mem.created) == 1


def test_curiosity_duplicate_proposal_not_executed(monkeypatch):
    """同一 tool+args の反復は実行せず、連続2回で打ち切り要約へ進む。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(None, [_tool_call("srv__search", {"q": "1"}, n=1)]),
            _collected(None, [_tool_call("srv__search", {"q": "1"}, n=2)]),
            _collected(None, [_tool_call("srv__search", {"q": "1"}, n=3)]),
        ],
        replies=[json.dumps({"summary": "調べた。", "satisfied": True, "unresolved": None}, ensure_ascii=False)],
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    # 1 回だけ実行、以降の同一提案はスキップ → 連続2回で打ち切り
    assert FakePool.instances[0].calls == [("srv__search", {"q": "1"})]
    assert len(eng.calls) == 3
    assert len(eng.prompts) == 1  # 要約 LLM 1回（done が無いのでフォールバック）
    assert len(mem.created) == 1
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []


def test_curiosity_reject_and_valid_same_batch_all_answered(monkeypatch):
    """同一バッチに却下と実行が混在しても全 tool_call_id に tool 応答が返る（400 回帰防止）。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(
                None,
                [
                    _tool_call("srv__ghost", {"x": "1"}, call_id="rej-1"),
                    _tool_call("srv__search", {"q": "1"}, call_id="ok-1"),
                ],
            ),
            _collected("調べ終わった。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == [("srv__search", {"q": "1"})]
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    assert len(mem.created) == 1


def test_curiosity_duplicate_same_batch_all_answered(monkeypatch):
    """同一バッチ内の重複提案を拒否しても全 tool_call_id に tool 応答が返る（400 回帰防止）。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        [
            _collected(
                None,
                [
                    _tool_call("srv__search", {"q": "1"}, call_id="d-1"),
                    _tool_call("srv__search", {"q": "1"}, call_id="d-2"),
                ],
            ),
            _collected("調べ終わった。"),
        ]
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == [("srv__search", {"q": "1"})]
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    assert len(mem.created) == 1


def test_curiosity_budget_exceeded_same_batch_all_answered(monkeypatch):
    """予算超過で打ち切っても同一バッチの残り tool_call_id に応答が返る（400 回帰防止）。"""
    from nous.application.chat.curiosity import _run_curiosity_exploration

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=1)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(
                None,
                [
                    _tool_call("srv__search", {"q": "1"}, call_id="b-1"),
                    _tool_call("srv__search", {"q": "2"}, call_id="b-2"),
                    _tool_call("srv__search", {"q": "3"}, call_id="b-3"),
                ],
            )
        ],
        replies=[json.dumps({"summary": "調べた。", "satisfied": True, "unresolved": None}, ensure_ascii=False)],
    )
    asyncio.run(_run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert FakePool.instances[0].calls == [("srv__search", {"q": "1"})]  # 予算内の 1 回だけ実行
    assert _unanswered_tool_ids(eng.messages_refs[-1]) == []
    assert len(mem.created) == 1


def test_curiosity_search_result_compacted(monkeypatch):
    """検索系結果は server__name リストに compact 化してから 800 字 cap する。"""
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    class SearchPool(FakePool):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            big = json.dumps({"results": [{"server": "Exa", "name": f"web_search_exa_{i}"} for i in range(200)]})
            return {"result": big, "isError": False}

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", SearchPool)
    captured: dict = {}

    async def fake_summarize(ctx, engine, persona, curiosity, results, summary=None):
        captured["results"] = results

    from nous.application.chat import curiosity as _curiosity_mod

    monkeypatch.setattr(_curiosity_mod, "_summarize_and_record", fake_summarize)
    eng = FakeLLMEngine(
        [
            _collected(None, [_tool_call("srv__search", {"q": "1"})]),
            _collected("調べ終わった。"),
        ]
    )
    asyncio.run(mod._run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    step_result = captured["results"][0]["result"]
    assert step_result.startswith("Exa__web_search_exa_0")
    assert not step_result.startswith("{")  # 生 JSON でなく compact 化済み
    assert len(step_result) <= _curiosity_mod._CURIOSITY_STEP_RESULT_MAX_CHARS


class FakeSpontEngine(FakeLLMEngine):
    """run_spontaneous 用: generate_spontaneous が固定結果を返す。"""

    def __init__(self, result, turns=None, replies=None):
        super().__init__(turns, replies)
        self._result = result

    async def generate_spontaneous(self, persona, system_prompt, memory_texts, current_state, prompt_override=""):
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

    eng = FakeSpontEngine(_spont_result(curiosity="雲の重さ"), [json.dumps({"monologue": "独り言だよ"})])
    asyncio.run(run_spontaneous(ctx, config, eng, 300.0))
    events = wiring_events.snapshot_after(0)
    assert len(events) == 1  # 本体独り言のみ。探索は BoomPool で静かに死ぬ
    assert "静かね" in events[0]["meta"]["text"]


class TestCompactSearchResultShapeGate:
    """汎用検索データを壊さない: ツールカタログ形状の証拠がある時だけ compact する。"""

    def test_hub_shape_compacted(self):
        from nous.application.chat.curiosity import _compact_search_result

        text = json.dumps({"results": [{"server": "Exa", "name": "web_search_exa"}]})
        assert _compact_search_result(text) == "Exa__web_search_exa"

    def test_tool_name_shape_compacted(self):
        from nous.application.chat.curiosity import _compact_search_result

        text = json.dumps({"tools": [{"tool_name": "search_tools"}, {"tool_name": "execute_tool"}]})
        assert _compact_search_result(text) == "search_tools\nexecute_tool"

    def test_generic_name_only_untouched(self):
        from nous.application.chat.curiosity import _compact_search_result

        text = json.dumps({"results": [{"name": "some_web_result", "url": "https://x"}]})
        assert _compact_search_result(text) == text

    def test_mixed_evidence_untouched(self):
        from nous.application.chat.curiosity import _compact_search_result

        text = json.dumps({"results": [{"server": "Exa", "name": "a"}, {"name": "b"}]})
        assert _compact_search_result(text) == text

    def test_empty_items_untouched(self):
        from nous.application.chat.curiosity import _compact_search_result

        text = json.dumps({"results": []})
        assert _compact_search_result(text) == text

    def test_non_json_untouched(self):
        from nous.application.chat.curiosity import _compact_search_result

        assert _compact_search_result("plain text") == "plain text"


def test_curiosity_step_result_capped_and_invariant(monkeypatch):
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    long_text = "あ" * 3000

    class LongPool(FakePool):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"result": long_text, "isError": False}

    monkeypatch.setattr("nous.infrastructure.mcp_client.MCPClientPool", LongPool)
    captured: dict = {}

    async def fake_summarize(ctx, engine, persona, curiosity, results, summary=None):
        captured["results"] = results

    from nous.application.chat import curiosity as _curiosity_mod

    monkeypatch.setattr(_curiosity_mod, "_summarize_and_record", fake_summarize)
    eng = FakeLLMEngine([_collected(None, [_tool_call("srv__search", {"q": "1"})]), _collected("done")])
    asyncio.run(mod._run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    assert len(captured["results"][0]["result"]) <= _curiosity_mod._CURIOSITY_STEP_RESULT_MAX_CHARS
    assert _curiosity_mod._CURIOSITY_STEP_RESULT_MAX_CHARS == 2000
    assert _curiosity_mod._EXPLORATION_RESULT_MAX_CHARS >= 2 * _curiosity_mod._CURIOSITY_STEP_RESULT_MAX_CHARS


def test_curiosity_summary_prompt_includes_multiple_steps(monkeypatch):
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    mem = FakeMemoryService()
    eng = FakeLLMEngine(
        turns=[
            _collected(None, [_tool_call("srv__search", {"q": "AAA"})]),
            _collected(None, [_tool_call("srv__search", {"q": "BBB"})]),
            _collected(None),  # 最終回答なし → 要約フォールバック
        ],
        replies=[json.dumps({"summary": "まとめ", "satisfied": True, "unresolved": None}, ensure_ascii=False)],
    )
    asyncio.run(mod._run_curiosity_exploration(_explorer_ctx(mem=mem), config, "herta", _spont_result(), eng))
    assert len(eng.calls) == 3
    assert len(eng.prompts) == 1
    prompt = eng.prompts[0]
    assert "AAA" in prompt and "BBB" in prompt  # 複数ステップが要約プロンプトに載る
    assert len(mem.created) == 1


class TestFormatResearchContext:
    """curiosity system に添える文脈ブロック（純関数）。"""

    def test_empty_inputs_returns_empty(self):
        from nous.application.chat.curiosity import _format_research_context

        assert _format_research_context(None, None, None) == ""
        assert _format_research_context([], {}, "") == ""

    def test_monologue_capped_at_500(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(None, None, "m" * 600)
        assert out.startswith("【さっきの独り言】")
        body = out.split("\n", 1)[1]
        assert len(body) == 500

    def test_memory_top5_only(self):
        from nous.application.chat.curiosity import _format_research_context

        mems = [f"m{i}" for i in range(7)]
        out = _format_research_context(mems, None, None)
        assert "- m4" in out  # 5件目まで載る
        assert "m5" not in out  # 6件目は落ちる

    def test_memory_block_capped_at_1200(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(["y" * 800, "z" * 800], None, None)
        block = out.split("\n", 1)[1]
        assert len(block) <= 1200

    def test_braces_in_memory_do_not_crash(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(["brace {x} and {y}"], None, None)
        assert "brace {x} and {y}" in out

    def test_section_order(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(["mem"], {"emotion": "calm"}, "mono")
        assert out.index("【さっきの独り言】") < out.index("【最近の記憶】") < out.index("【今の気分】")
        assert "感情: calm" in out

    def test_recent_turns_section_first(self):
        from nous.application.chat.curiosity import _format_research_context

        turns = [{"role": "user", "content": "雲の重さは？"}, {"role": "assistant", "content": "調べてみるわ"}]
        out = _format_research_context(["mem"], {"emotion": "calm"}, "mono", recent_turns=turns)
        assert out.startswith("【最近の会話】")
        assert "user: 雲の重さは？" in out
        assert "assistant: 調べてみるわ" in out
        assert (
            out.index("【最近の会話】")
            < out.index("【さっきの独り言】")
            < out.index("【最近の記憶】")
            < out.index("【今の気分】")
        )

    def test_recent_turns_capped_at_four_and_roles_filtered(self):
        from nous.application.chat.curiosity import _format_research_context

        turns = [{"role": "user", "content": f"u{i}"} for i in range(5)]
        turns.insert(2, {"role": "system", "content": "sys-turn"})
        out = _format_research_context(None, None, None, recent_turns=turns)
        assert "sys-turn" not in out  # user/assistant 以外は除外
        assert "u0" not in out  # 直近4件に丸められ、最古の1件は落ちる
        assert "u1" in out and "u4" in out

    def test_recent_turns_content_capped_at_200(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(None, None, None, recent_turns=[{"role": "user", "content": "x" * 300}])
        assert "x" * 200 in out
        assert "x" * 201 not in out

    def test_recent_turns_none_omits_section(self):
        from nous.application.chat.curiosity import _format_research_context

        out = _format_research_context(["mem"], None, "mono", recent_turns=None)
        assert "【最近の会話】" not in out
        assert out.startswith("【さっきの独り言】")


def test_curiosity_system_includes_context_without_format_crash(monkeypatch):
    """system は base.format(persona) の後に文脈を連結する（本文の {} で落ちない）。"""
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([_collected(None, [])])
    asyncio.run(
        mod._run_curiosity_exploration(
            _explorer_ctx(),
            config,
            "herta",
            _spont_result(),
            eng,
            memory_texts=["記憶A {brace}", "記憶B"],
            current_state={"emotion": "calm", "emotion_intensity": 0.3, "body_state": {"fatigue": 1}, "elapsed": "5分"},
        )
    )
    system = eng.calls[0]["system"]
    assert "あなたは herta です" in system  # base は format 済み
    assert "【さっきの独り言】" in system and "静かね" in system
    assert "【最近の記憶】" in system and "記憶A {brace}" in system
    assert "【今の気分】" in system and "感情: calm" in system


def test_curiosity_system_omits_context_when_not_passed(monkeypatch):
    from nous.application.chat import introspection as mod

    config = _patch_env(monkeypatch, enabled=True, max_tool_calls=5)
    FakePool.instances.clear()
    wiring_events.clear()
    import asyncio

    eng = FakeLLMEngine([_collected(None, [])])
    asyncio.run(mod._run_curiosity_exploration(_explorer_ctx(), config, "herta", _spont_result(), eng))
    system = eng.calls[0]["system"]
    assert "【最近の記憶】" not in system
    assert "【今の気分】" not in system
