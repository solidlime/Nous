"""tests/unit/test_repair_step.py — RepairStep（毎ターンキャラ判定＋違反時修復）の単体テスト。"""

from __future__ import annotations

from typing import Any

from nous.application.chat.events import ResponseReplacedSSE
from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.repair import RepairStep
from nous.infrastructure.llm.base import LLMMessage


class _Config:
    """judge_character / RepairStep が必要とする最小設定モック。"""

    character_judge_enabled = True
    character_repair_max_attempts = 2
    provider = "test"
    temperature = 0.7
    max_tokens = 512
    extract_model = ""

    def get_effective_api_key(self) -> str:
        return "key"

    def get_effective_model(self) -> str:
        return "m"

    def get_effective_base_url(self) -> str:
        return ""


def _turn_ctx(response: str = "違反のある応答", tool_calls_log: list[dict] | None = None) -> ChatTurnContext:
    ctx = ChatTurnContext(session_id="main", user_message="こんにちは")
    ctx.system_prompt = "キャラ定義"
    ctx.full_response = response
    ctx.tool_calls_log = tool_calls_log or []
    return ctx


def _messages() -> list[LLMMessage]:
    return [LLMMessage(role="user", content="こんにちは")]


def _patch(monkeypatch, judgments: list[dict | None], text: str = "修復済み応答") -> dict[str, Any]:
    """repair モジュール内の judge_character / get_provider / collect_text を差し替える。

    judgments: judge_character の呼び出し順に返す値。尽きたら最後の値を返す。
    """
    from nous.application.chat.pipeline import repair

    calls = {"judge": 0, "provider": 0, "collect": 0}

    async def _fake_judge(config: Any, persona_identity: str, response: str) -> dict | None:
        idx = min(calls["judge"], len(judgments) - 1)
        calls["judge"] += 1
        return judgments[idx]

    class _FakeProvider:
        pass

    def _fake_get_provider(*args: Any, **kwargs: Any) -> _FakeProvider:
        calls["provider"] += 1
        return _FakeProvider()

    async def _fake_collect_text(provider: Any, *, messages: list[LLMMessage], **kwargs: Any) -> str:
        calls["collect"] += 1
        calls["last_messages"] = messages
        return text

    monkeypatch.setattr(repair, "judge_character", _fake_judge)
    monkeypatch.setattr(repair, "get_provider", _fake_get_provider)
    monkeypatch.setattr(repair, "collect_text", _fake_collect_text)
    return calls


async def test_disabled_judge_skips_everything(monkeypatch) -> None:
    config = _Config()
    config.character_judge_enabled = False
    calls = _patch(monkeypatch, judgments=[{"violation": "tone", "detail": "x"}])
    events = [ev async for ev in RepairStep().run(None, config, _messages(), _turn_ctx())]
    assert events == []
    assert calls["judge"] == 0
    assert calls["collect"] == 0


async def test_zero_attempts_skips_everything(monkeypatch) -> None:
    config = _Config()
    config.character_repair_max_attempts = 0
    calls = _patch(monkeypatch, judgments=[{"violation": "tone", "detail": "x"}])
    events = [ev async for ev in RepairStep().run(None, config, _messages(), _turn_ctx())]
    assert events == []
    assert calls["judge"] == 0


async def test_empty_response_skips_everything(monkeypatch) -> None:
    calls = _patch(monkeypatch, judgments=[{"violation": "tone", "detail": "x"}])
    events = [ev async for ev in RepairStep().run(None, _Config(), _messages(), _turn_ctx(response=""))]
    assert events == []
    assert calls["judge"] == 0


async def test_no_violation_no_regeneration_no_sse(monkeypatch) -> None:
    calls = _patch(monkeypatch, judgments=[{"violation": "none", "detail": ""}])
    turn_ctx = _turn_ctx(response="問題ない応答")
    events = [ev async for ev in RepairStep().run(None, _Config(), _messages(), turn_ctx)]
    assert events == []
    assert calls["collect"] == 0
    assert turn_ctx.full_response == "問題ない応答"


async def test_violation_triggers_regeneration_and_replacement(monkeypatch) -> None:
    calls = _patch(
        monkeypatch,
        judgments=[
            {"violation": "tone", "detail": "口調が崩れている"},
            {"violation": "none", "detail": ""},
        ],
        text="修復済み応答",
    )
    turn_ctx = _turn_ctx(
        response="違反のある応答",
        tool_calls_log=[{"id": "t1", "name": "memory_search", "input": {}, "result": "検索結果本文"}],
    )
    events = [ev async for ev in RepairStep().run(None, _Config(), _messages(), turn_ctx)]
    assert calls["provider"] == 1
    assert calls["collect"] == 1
    assert turn_ctx.full_response == "修復済み応答"
    assert len(events) == 1
    assert isinstance(events[0], ResponseReplacedSSE)
    assert events[0].content == "修復済み応答"
    assert events[0].violation == "none"
    # 修復プロンプトに元応答・違反詳細・ツール結果が含まれること
    last_user = calls["last_messages"][-1]
    assert last_user.role == "user"
    assert "違反のある応答" in last_user.content
    assert "tone" in last_user.content
    assert "口調が崩れている" in last_user.content
    assert "memory_search" in last_user.content
    assert "検索結果本文" in last_user.content


async def test_regeneration_failure_keeps_original_no_sse(monkeypatch) -> None:
    from nous.application.chat.pipeline import repair

    async def _fake_judge(config: Any, persona_identity: str, response: str) -> dict | None:
        return {"violation": "tone", "detail": "x"}

    def _fake_get_provider(*args: Any, **kwargs: Any) -> object:
        return object()

    async def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(repair, "judge_character", _fake_judge)
    monkeypatch.setattr(repair, "get_provider", _fake_get_provider)
    monkeypatch.setattr(repair, "collect_text", _boom)

    turn_ctx = _turn_ctx(response="元の応答")
    events = [ev async for ev in RepairStep().run(None, _Config(), _messages(), turn_ctx)]
    assert events == []
    assert turn_ctx.full_response == "元の応答"


async def test_attempts_exhausted_adopts_last_candidate(monkeypatch) -> None:
    calls = _patch(
        monkeypatch,
        judgments=[
            {"violation": "tone", "detail": "d1"},
            {"violation": "character", "detail": "d2"},
            {"violation": "character", "detail": "d2"},
        ],
        text="候補",
    )
    config = _Config()
    config.character_repair_max_attempts = 2
    turn_ctx = _turn_ctx(response="違反のある応答")
    events = [ev async for ev in RepairStep().run(None, config, _messages(), turn_ctx)]
    assert calls["collect"] == 2
    assert turn_ctx.full_response == "候補"
    # 上限到達時も最後の候補を採用して1回だけ置換を通知する
    assert len(events) == 1
    assert isinstance(events[0], ResponseReplacedSSE)
    assert events[0].violation == "character"
    assert events[0].detail == "d2"


async def test_judge_malformed_output_keeps_original(monkeypatch) -> None:
    """judge が不正 JSON / 不正 violation を返したら判定なし扱いで修復しない。"""
    calls = _patch(
        monkeypatch, judgments=[None]
    )  # judge_character が None を返すケース（内部で JSON パース失敗済み想定）
    turn_ctx = _turn_ctx(response="違反の可能性がある応答")
    events = [ev async for ev in RepairStep().run(None, _Config(), _messages(), turn_ctx)]
    assert events == []
    assert calls["collect"] == 0
    assert turn_ctx.full_response == "違反の可能性がある応答"


async def test_judge_invalid_json_returns_none(monkeypatch) -> None:
    """judge_character は不正 JSON / 不正 violation を None に落とす（非破壊）。"""
    from nous.application.chat import character_judge

    async def _fake_collect(provider: Any, *, messages: list[LLMMessage], **kwargs: Any) -> str:
        return "ぜんぜんJSONじゃない出力"

    monkeypatch.setattr(character_judge, "collect_text", _fake_collect)
    assert await character_judge.judge_character(_Config(), "アイデンティティ", "応答テキスト") is None
