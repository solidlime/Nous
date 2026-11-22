"""backlog #41: 相手モデル — プロフィールとは別の ``them`` ブロック（最近のやりとり3行）。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.domain.shared.result import Success


def _event(user: str, assistant: str, stamp: str = "2026-01-01T00:00:00+00:00") -> SimpleNamespace:
    """実際の発話イベントは chat.message / chat.llm_response に分かれる。"""
    return SimpleNamespace(
        event_type="chat.message", timestamp=stamp, detail=json.dumps({"content": user}, ensure_ascii=False)
    )


def _reply(assistant: str, stamp: str) -> SimpleNamespace:
    return SimpleNamespace(
        event_type="chat.llm_response", timestamp=stamp, detail=json.dumps({"content": assistant}, ensure_ascii=False)
    )


def _exchange(index: int, user: str, assistant: str) -> list[SimpleNamespace]:
    stamp = f"2026-01-01T00:0{index}:00+00:00"
    return [_event(user, assistant, stamp), _reply(assistant, stamp)]


def _prompt(events: list | None, blocks: dict | None = None) -> str:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s"
    ctx.memory_service.get_profile_blocks.return_value = Success(blocks or {})
    # 呼び出しは event_type ごとに 1 回ずつ。モックもそのフィルタを再現する。
    ctx._session_event_repo.get_by_persona.side_effect = lambda persona, event_type=None, limit=12: [
        e for e in (events or []) if e.event_type == event_type
    ]
    config = MagicMock()
    config.system_prompt = ""
    config.enabled_skills = []
    turn_ctx = ChatTurnContext(session_id="s", user_message="やあ")
    PromptBuildStep().run(ctx, config, turn_ctx)
    # them ブロックは揮発側（[NOUS CONTEXT]）に載る
    return turn_ctx.system_prompt + "\n" + turn_ctx.volatile_context


def test_them_block_folds_last_three_exchanges_in_order():
    events = _exchange(1, "1通目", "1返事") + _exchange(2, "2通目", "2返事") + _exchange(3, "3通目", "3返事")
    events += _exchange(4, "4通目", "4返事")

    prompt = _prompt(events)

    assert "【最近のやりとり】" in prompt
    section = prompt.split("【最近のやりとり】")[1]
    lines = [ln for ln in section.splitlines() if ln.startswith("- 相手: ")]
    assert len(lines) == 3
    # 古い順に並べ、古い 1通目 は落ちる
    assert "2通目" in lines[0] and "2返事" in lines[0]
    assert "3通目" in lines[1]
    assert "4通目" in lines[2] and "4返事" in lines[2]


def test_them_block_pairs_user_with_my_reply():
    prompt = _prompt(_exchange(1, "今日は寒いね", "そうだね"))

    assert "- 相手: 今日は寒いね / 私: そうだね" in prompt


def test_them_block_clips_long_utterances():
    prompt = _prompt(_exchange(1, "あ" * 100, "い" * 100))

    assert "あ" * 60 + "…" in prompt
    assert "あ" * 61 not in prompt


def test_them_block_absent_without_events():
    assert "【最近のやりとり】" not in _prompt([])


def test_them_block_absent_when_repo_missing():
    ctx = MagicMock(spec=["persona", "memory_service"])
    ctx.persona = "herta"
    ctx.memory_service.get_profile_blocks.return_value = Success({})
    turn_ctx = ChatTurnContext(session_id="s", user_message="やあ")
    config = MagicMock(system_prompt="", enabled_skills=[])

    PromptBuildStep().run(ctx, config, turn_ctx)

    assert "【最近のやりとり】" not in turn_ctx.system_prompt


def test_me_block_unchanged_next_to_them_block():
    prompt = _prompt(_exchange(1, "やあ", "どうした"), {"me": {"content": "私はヘルタ。"}})

    assert "【自己像】\n私はヘルタ。" in prompt
    assert prompt.index("【自己像】") < prompt.index("【最近のやりとり】")
