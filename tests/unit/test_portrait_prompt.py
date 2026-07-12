"""Tests for PortraitPromptBuilder."""

from __future__ import annotations

from nous.domain.persona.entities import PersonaState
from nous.domain.persona.portrait_prompt import (
    _EMOTION_ADJECTIVES,
    _NEGATIVE_PROMPT,
    PortraitPromptBuilder,
)


class TestPortraitPromptBuilder:
    """Suite of unit tests for PortraitPromptBuilder.build()."""

    def _make_persona(
        self,
        persona: str = "test_char",
        appearance: str | None = "silver hair, red eyes",
        emotion: str = "neutral",
    ) -> PersonaState:
        return PersonaState(
            persona=persona,
            appearance=appearance,
            emotion=emotion,
        )

    # ------------------------------------------------------------------
    # LLM mode (scene provided)
    # ------------------------------------------------------------------

    def test_llm_mode_contains_scene_text(self) -> None:
        """LLM mode: prompt must include the scene description."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="at the beach watching the sunset",
        )
        assert "at the beach watching the sunset" in prompt

    def test_llm_mode_contains_char_name(self) -> None:
        """LLM mode: prompt must include the persona name."""
        persona = self._make_persona(persona="Shiro")
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="in a garden",
        )
        assert "Shiro" in prompt

    def test_llm_mode_with_equipment(self) -> None:
        """LLM mode: equipment_desc appears in prompt."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="castle courtyard",
            equipment_desc="wearing a silver armor",
        )
        assert "wearing a silver armor" in prompt

    def test_llm_mode_missing_equipment(self) -> None:
        """LLM mode: no equipment line when equipment_desc is None."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="forest path",
            equipment_desc=None,
        )
        assert "wearing a silver armor" not in prompt
        # Scene should directly follow appearance
        assert "forest path" in prompt

    def test_llm_mode_missing_appearance(self) -> None:
        """LLM mode: no appearance line when persona.appearance is None."""
        persona = self._make_persona(appearance=None)
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="mountain peak",
            equipment_desc="carrying a staff",
        )
        assert "silver hair" not in prompt
        assert "carrying a staff" in prompt
        assert "mountain peak" in prompt

    def test_llm_mode_missing_appearance_and_equipment(self) -> None:
        """LLM mode: only emotion line + scene + quality tags remain."""
        persona = self._make_persona(appearance=None)
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="empty void",
            equipment_desc=None,
        )
        # Should have: 1girl, ..., expression  +  scene  +  quality tags
        assert "empty void" in prompt
        assert "masterpiece, high score, great score, absurdres" in prompt

    # ------------------------------------------------------------------
    # Auto mode (no scene)
    # ------------------------------------------------------------------

    def test_auto_mode_contains_looking_at_viewer(self) -> None:
        """Auto mode: 'looking at viewer' must be present."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(persona=persona)
        assert "looking at viewer" in prompt

    def test_auto_mode_no_scene_text(self) -> None:
        """Auto mode: no scene description should appear."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(persona=persona)
        assert "at the beach" not in prompt

    def test_auto_mode_with_body_state(self) -> None:
        """Auto mode: body_state desc appears when provided."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            body_state={"fatigue": 0.9, "warmth": 0.8},
        )
        assert "tired" in prompt
        assert "warm" in prompt

    def test_auto_mode_body_state_none(self) -> None:
        """Auto mode: no body_state line when body_state is None."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            body_state=None,
        )
        assert "tired" not in prompt
        assert "warm" not in prompt
        assert "cold" not in prompt

    def test_auto_mode_missing_appearance(self) -> None:
        """Auto mode: no appearance line when persona.appearance is None."""
        persona = self._make_persona(appearance=None)
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            body_state={"fatigue": 0.6},
        )
        assert "silver hair" not in prompt
        assert "tired" in prompt
        assert "looking at viewer" in prompt

    def test_auto_mode_with_equipment(self) -> None:
        """Auto mode: equipment_desc appears in prompt."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            equipment_desc="wearing a black coat",
        )
        assert "wearing a black coat" in prompt

    def test_auto_mode_missing_equipment(self) -> None:
        """Auto mode: no equipment line when equipment_desc is None."""
        persona = self._make_persona()
        prompt, _ = PortraitPromptBuilder.build(persona=persona)
        assert "wearing a black coat" not in prompt

    # ------------------------------------------------------------------
    # Emotion → adjective mapping
    # ------------------------------------------------------------------

    def test_all_emotions_produce_correct_adjective(self) -> None:
        """Each known emotion maps to its expected adjective."""
        for emotion, expected_adj in _EMOTION_ADJECTIVES.items():
            persona = self._make_persona(emotion=emotion)
            prompt, _ = PortraitPromptBuilder.build(persona=persona)
            assert f"{expected_adj} expression" in prompt, f"emotion={emotion!r} expected adj={expected_adj!r}"

    def test_unknown_emotion_falls_back_to_calm(self) -> None:
        """Unknown emotion string uses 'calm' as fallback."""
        persona = self._make_persona(emotion="nonexistent")
        prompt, _ = PortraitPromptBuilder.build(persona=persona)
        assert "calm expression" in prompt

    # ------------------------------------------------------------------
    # Negative prompt
    # ------------------------------------------------------------------

    def test_negative_prompt_always_identical(self) -> None:
        """Negative prompt must always be the same string."""
        persona_1 = self._make_persona(emotion="joy")
        persona_2 = self._make_persona(emotion="anger")

        _, neg_1 = PortraitPromptBuilder.build(
            persona=persona_1,
            scene="sunset",
        )
        _, neg_2 = PortraitPromptBuilder.build(persona=persona_2)

        assert neg_1 == _NEGATIVE_PROMPT
        assert neg_2 == _NEGATIVE_PROMPT
        assert neg_1 == neg_2

    # ------------------------------------------------------------------
    # Structural checks
    # ------------------------------------------------------------------

    def test_output_is_tuple_of_two_strings(self) -> None:
        """build() always returns a (prompt, negative) tuple."""
        persona = self._make_persona()
        result = PortraitPromptBuilder.build(persona=persona)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_llm_mode_includes_quality_tags(self) -> None:
        """Both modes include the standard quality suffix."""
        persona = self._make_persona()
        prompt_llm, _ = PortraitPromptBuilder.build(
            persona=persona,
            scene="test scene",
        )
        prompt_auto, _ = PortraitPromptBuilder.build(persona=persona)
        quality = "masterpiece, high score, great score, absurdres"
        assert quality in prompt_llm
        assert quality in prompt_auto

    def test_body_state_no_matching_keys(self) -> None:
        """Body state with values below thresholds produces no desc line."""
        persona = self._make_persona(appearance="green eyes")
        prompt, _ = PortraitPromptBuilder.build(
            persona=persona,
            body_state={"fatigue": 0.3, "warmth": 0.5, "arousal": 0.4},
        )
        # Should not have any body-state desc — falls through to
        # looking at viewer directly after appearance
        assert "looking at viewer" in prompt
        assert "tired" not in prompt
        assert "warm" not in prompt
        assert "cold" not in prompt
        assert "energetic" not in prompt
