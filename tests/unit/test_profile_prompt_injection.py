"""B-4: system prompt への常載プロフィールブロック注入（me → user 固定順）."""

from __future__ import annotations

from unittest.mock import MagicMock

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.domain.shared.result import Failure, Success


def _ctx(blocks: object) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s"
    if isinstance(blocks, Exception):
        ctx.memory_service.get_profile_blocks.side_effect = blocks
    else:
        ctx.memory_service.get_profile_blocks.return_value = blocks
    return ctx


def _config(compress_mode: str = "auto") -> MagicMock:
    cfg = MagicMock()
    cfg.system_prompt = ""
    cfg.enabled_skills = []
    cfg.compress_mode = compress_mode
    return cfg


def _prompt(blocks: object, compress_mode: str = "auto") -> str:
    turn_ctx = ChatTurnContext(session_id="s", user_message="やあ")
    PromptBuildStep().run(_ctx(blocks), _config(compress_mode), turn_ctx)
    return turn_ctx.system_prompt


def _blocks(**rows: str) -> Success:
    return Success({name: {"content": content} for name, content in rows.items()})


def test_both_blocks_injected_me_before_user():
    prompt = _prompt(_blocks(me="私はヘルタ。", user="ユーザーはマダム。"))

    assert "【自己像】\n私はヘルタ。" in prompt
    assert "【ユーザー像】\nユーザーはマダム。" in prompt
    assert prompt.index("【自己像】") < prompt.index("【ユーザー像】")
    # 動的領域（__STATIC_END__ 以降）に置かれる
    assert prompt.index("__STATIC_END__") < prompt.index("【自己像】")


def test_missing_block_is_omitted():
    prompt = _prompt(_blocks(user="ユーザーはマダム。"))

    assert "【自己像】" not in prompt
    assert "【ユーザー像】" in prompt


def test_no_blocks_no_section():
    assert "【自己像】" not in _prompt(Success({}))


def test_light_mode_still_injects():
    prompt = _prompt(_blocks(me="私はヘルタ。"), compress_mode="light")

    assert "【自己像】" in prompt


def test_failure_result_skipped_silently():
    assert "【自己像】" not in _prompt(Failure(ValueError("db down")))


def test_exception_skipped_silently():
    assert "【自己像】" not in _prompt(RuntimeError("boom"))
