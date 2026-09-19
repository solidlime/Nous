"""Tests for AppContext._on_tool_called_record_conversation.

tool.called をユーザー由来の対話活動として last_conversation_time に記録する
ハンドラの直接テスト。内省（curiosity）由来は source タグまたはサイクル中フラグで除外する。
"""

from __future__ import annotations

from types import SimpleNamespace

from nous.application.chat.curiosity import _run_curiosity_exploration
from nous.application.use_cases import AppContext

# bound でない実メソッド。fake_self を第一引数に渡して呼ぶ。
_HANDLER = AppContext._on_tool_called_record_conversation


class _RecordingPersonaService:
    """record_conversation_time の呼び出しを記録するスタブ。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record_conversation_time(self, persona: str) -> None:
        self.calls.append(persona)


class _RaisingPersonaService:
    def record_conversation_time(self, persona: str) -> None:
        raise RuntimeError("boom")


class _FakeCtx:
    """AppContext のハンドラが触る最小属性だけ持つスタブ。"""

    def __init__(
        self,
        persona_service: object | None = None,
        introspection_active: bool = False,
    ) -> None:
        self.persona_service = persona_service or _RecordingPersonaService()
        self._introspection_tool_active = introspection_active


async def test_direct_event_records_conversation_time() -> None:
    persona_service = _RecordingPersonaService()
    ctx = _FakeCtx(persona_service=persona_service)

    await _HANDLER(ctx, "tool.called", {"persona": "nous", "tool_name": "memory_search"})

    assert persona_service.calls == ["nous"]


async def test_introspection_source_is_ignored() -> None:
    persona_service = _RecordingPersonaService()
    ctx = _FakeCtx(persona_service=persona_service)

    await _HANDLER(ctx, "tool.called", {"persona": "nous", "source": "introspection"})

    assert persona_service.calls == []


async def test_introspection_flag_suppresses_source_less_event() -> None:
    persona_service = _RecordingPersonaService()
    ctx = _FakeCtx(persona_service=persona_service, introspection_active=True)

    await _HANDLER(ctx, "tool.called", {"persona": "nous"})

    assert persona_service.calls == []


async def test_missing_or_invalid_persona_is_ignored() -> None:
    persona_service = _RecordingPersonaService()
    ctx = _FakeCtx(persona_service=persona_service)

    await _HANDLER(ctx, "tool.called", {})
    await _HANDLER(ctx, "tool.called", {"persona": ""})
    await _HANDLER(ctx, "tool.called", {"persona": None})
    await _HANDLER(ctx, "tool.called", {"persona": 123})

    assert persona_service.calls == []


async def test_persona_service_error_is_swallowed() -> None:
    ctx = _FakeCtx(persona_service=_RaisingPersonaService())

    # 例外が外に漏れないこと。
    await _HANDLER(ctx, "tool.called", {"persona": "nous"})


async def test_introspection_flag_cleared_when_pool_construction_raises(monkeypatch) -> None:
    """MCPClientPool 構築で例外が出ても finally でフラグが必ず False に戻ること。"""
    import nous.infrastructure.mcp_client as mcp_client

    class _BoomPool:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("pool boom")

    monkeypatch.setattr(mcp_client, "MCPClientPool", _BoomPool)
    monkeypatch.setattr(
        "nous.config.settings.get_settings",
        lambda: SimpleNamespace(explorer=SimpleNamespace(enabled=True, max_tool_calls=1)),
    )

    ctx = _FakeCtx()
    config = SimpleNamespace(brain_monologue_enabled=True, mcp_servers=[], disabled_tools=[])
    result = SimpleNamespace(curiosity="何か調べたい", monologue=None)

    await _run_curiosity_exploration(ctx, config, "nous", result, engine=None)

    assert ctx._introspection_tool_active is False
