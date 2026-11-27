"""#39: 感情 if-then は <current_state> 内の「向き:」1 行として注入される。"""

from __future__ import annotations

from unittest.mock import MagicMock

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.prompt import PromptBuildStep

HEADER = "向き: "


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s"
    return ctx


def _config(texts: dict | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.system_prompt = ""
    cfg.enabled_skills = []
    cfg.emotion_hint_low = 0.35
    cfg.emotion_hint_high = 0.7
    cfg.emotion_hint_texts = texts or {}
    return cfg


def _run(state_raw: dict, texts: dict | None = None, context_section: tuple[str, str] = ("", "")) -> str:
    turn_ctx = ChatTurnContext(session_id="s", user_message="やあ")
    turn_ctx.state_raw = state_raw
    turn_ctx.context_section = context_section
    PromptBuildStep().run(_ctx(), _config(texts), turn_ctx)
    # 感情行は揮発側（会話後方の [NOUS CONTEXT]）に載る
    return turn_ctx.system_prompt + "\n" + turn_ctx.volatile_context


def test_emotion_line_injected_once():
    prompt = _run({"emotion": "joy", "emotion_intensity": 0.9})

    assert prompt.count(HEADER) == 1


def test_emotion_line_sits_inside_current_state():
    """向き は <current_state> の末尾 1 行（記憶ブロックには混ぜない）。"""
    prompt = _run({"emotion": "joy", "emotion_intensity": 0.9}, context_section=("感情: joy（強い）", ""))

    assert HEADER in prompt.split("<current_state>", 1)[1].split("</current_state>", 1)[0]
    assert prompt.count(HEADER) == 1


def test_no_emotion_no_line():
    assert HEADER not in _run({})
    assert HEADER not in _run({"emotion": "", "emotion_intensity": 0.9})


def test_config_texts_override():
    prompt = _run({"emotion": "joy", "emotion_intensity": 0.9}, texts={"joy": ["A", "B", "C"]})

    assert f"{HEADER}C" in prompt
