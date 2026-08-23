"""Gap documentation tests: response validation gaps in the chat pipeline.

These tests document that response validation was historically absent from
PostProcessStep. After adding ResponseValidator (response_validator.py) and
integrating it into PostProcessStep.run(), some tests now verify detection
rather than absence.
"""

import inspect
import textwrap


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

    def test_author_note_no_contradiction_check(self):
        """Author's Note injection code has no contradiction detection."""
        from nous.application.chat.pipeline import prompt as prompt_module

        source = textwrap.dedent(inspect.getsource(prompt_module))
        # Check that there's no contradiction detection logic
        # near the Author's Note injection
        contradiction_keywords = [
            "contradiction",
            "inconsist",
            "conflict",
            "validate",
            "sanitize",
        ]
        author_note_section = source[source.find("Author's Note") :]
        for keyword in contradiction_keywords:
            assert keyword not in author_note_section.lower(), f"Author's Note code unexpectedly contains '{keyword}'"
