"""Gap documentation tests: response validation gaps in the chat pipeline.

These tests document that response validation was historically absent from
PostProcessStep. After adding ResponseValidator (response_validator.py) and
integrating it into PostProcessStep.run(), some tests now verify detection
rather than absence.
"""

import inspect
import textwrap

import pytest


class TestPerTurnJudgeRemoved:
    """毎ターンのキャラ判定器（RepairStep / character_judge）は 2026-11 に全廃した。

    遅延対策: 判定は毎ターン外部 LLM を 1〜5 往復叩き、得られるのは
    ``{"violation": "none"}`` だけだった。drift 記憶の生成・注入も同じ経路で
    消えている（復活させないための見張り）。
    """

    def test_repair_module_is_gone(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("nous.application.chat.pipeline.repair")

    def test_character_judge_module_is_gone(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("nous.application.chat.character_judge")

    def test_run_does_not_call_judge_character(self):
        from nous.application.chat.pipeline.post import PostProcessStep

        source = inspect.getsource(PostProcessStep.run)
        assert "judge_character" not in source
        assert "_with_drift" not in source

    def test_memory_payload_has_no_drift(self):
        """MemoryLLM の payload に drift を載せる経路が無いこと。"""
        from nous.application.chat.pipeline.context import ChatTurnContext
        from nous.application.chat.pipeline.post import _memory_payload

        turn_ctx = ChatTurnContext(session_id="main", user_message="やあ")
        turn_ctx.full_response = "おや、あんたか"
        assert _memory_payload(turn_ctx) == {"user": "やあ", "assistant": "おや、あんたか"}
        assert not hasattr(turn_ctx, "drift")

    def test_memory_llm_still_called(self):
        from nous.application.chat.pipeline.post import PostProcessStep

        source = inspect.getsource(PostProcessStep.run)
        assert "run_memory_llm" in source, "MemoryLLM extraction must remain per-turn"

    def test_drift_injection_is_gone(self):
        from nous.application.chat.pipeline import context_loader

        source = inspect.getsource(context_loader)
        assert "character_drift" not in source, "drift 注入は廃止済み（判定器が無いので生成経路も無い）"


class TestCharacterConsistencyGap:
    """R2: Character contradiction detection gap."""

    def test_no_character_consistency_check_exists(self):
        """PostProcessStep should have no dedicated character consistency method.

        The validate_response() call added to run() is a function call,
        not a method of PostProcessStep itself.
        """
        from nous.application.chat.pipeline.post import PostProcessStep

        step = PostProcessStep()
        attrs = dir(step)
        validation_methods = [
            a
            for a in attrs
            if "valid" in a.lower()
            or "character" in a.lower()
            or "contradiction" in a.lower()
            or "sanitize" in a.lower()
        ]
        assert validation_methods == [], (
            f"PostProcessStep has unexpected validation-related attributes: {validation_methods}"
        )

    def test_garbled_text_now_detected(self):
        """After task 3, garbled text IS detected by ResponseValidator.

        Verify that validate_response() catches garbled text, and that
        PostProcessStep.run() integrates the validator.
        """
        from nous.application.chat.response_validator import validate_response

        # Garbled text with N'Ko characters (U+07CA-U+07CE)
        # 5 garbled chars in ~22 char text → ~22% > 5% threshold
        garbled_text = "正常なテキストです。\u07ca\u07cb\u07cc\u07cd\u07ceが混ざっています。"
        warnings = validate_response(garbled_text)
        assert any("Garbled" in w for w in warnings), f"Expected garbled warning, got: {warnings}"

        # Verify integration: PostProcessStep.run() calls validate_response
        from nous.application.chat.pipeline.post import PostProcessStep

        source = textwrap.dedent(inspect.getsource(PostProcessStep.run))
        assert "validate_response" in source, "PostProcessStep.run() must call validate_response()"
