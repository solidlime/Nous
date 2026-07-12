"""Tests for PortraitGenerationService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.config.settings import PortraitGenerationConfig
from nous.domain.persona.entities import PersonaState
from nous.domain.persona.portrait_prompt import (
    PortraitPromptBuilder,
    _intensity_modifier,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> PortraitGenerationConfig:
    """Create a PortraitGenerationConfig with sensible defaults."""
    defaults: dict[str, object] = {
        "enabled": True,
        "provider": "comfyui",
        "comfyui_url": "http://localhost:8188",
        "auto_generate": True,
        "generate_interval_min": 10,
        "size": "512x512",
        "quality": "standard",
        "emotion_threshold": 0.3,
        "max_monthly_budget": 0.0,  # 0 = no limit
    }
    defaults.update(overrides)
    return PortraitGenerationConfig(**defaults)


def _make_persona(
    persona: str = "test_char",
    emotion: str = "joy",
    emotion_intensity: float = 0.7,
    appearance: str | None = "silver hair, red eyes",
    **body_kw: object,
) -> PersonaState:
    """Create a PersonaState for testing."""
    return PersonaState(
        persona=persona,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
        appearance=appearance,
        **body_kw,
    )


# ---------------------------------------------------------------------------
# Fixture: mock provider (via factory)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_provider():
    """Return an AsyncMock that looks like a ComfyUIProvider."""
    provider = MagicMock()
    provider.provider_name = "comfyui"
    provider.generate = AsyncMock(
        return_value=[
            MagicMock(base64="dGVzdF9pbWFnZV9kYXRh", revised_prompt="", size="512x512"),
        ]
    )
    provider.health_check = AsyncMock(return_value=True)
    return provider


@pytest.fixture
def service(mock_provider):
    """Return a PortraitGenerationService with a mocked provider."""
    with patch(
        "nous.application.portrait.service.get_image_gen_provider",
        return_value=mock_provider,
    ):
        svc = _make_service()
        yield svc


def _make_service(**config_overrides: object):
    """Helper to instantiate the service (must be called inside a factory patch)."""
    from nous.application.portrait.service import PortraitGenerationService

    config = _make_config(**config_overrides)
    return PortraitGenerationService(config)


# ===========================================================================
# Tests: generate() — success
# ===========================================================================


class TestGenerateSuccess:
    """Happy-path generation scenarios."""

    @pytest.mark.asyncio
    async def test_generate_returns_image_and_prompts(self, service):
        """Successful generation returns base64 image + prompt + negative."""
        persona = _make_persona()
        result = await service.generate(persona=persona, scene="beach sunset")

        assert "image_base64" in result
        assert result["image_base64"] == "dGVzdF9pbWFnZV9kYXRh"
        assert "prompt" in result
        assert isinstance(result["prompt"], str)
        assert "negative_prompt" in result
        assert isinstance(result["negative_prompt"], str)
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_generate_calls_provider_with_correct_params(self, service, mock_provider):
        """Provider.generate is called with prompt, size, and quality from config."""
        persona = _make_persona()
        await service.generate(persona=persona, scene="garden")

        mock_provider.generate.assert_awaited_once()
        _call_kwargs = mock_provider.generate.call_args[1]
        assert _call_kwargs["size"] == "512x512"
        assert _call_kwargs["quality"] == "standard"

    @pytest.mark.asyncio
    async def test_generate_no_scene_auto_mode(self, service, mock_provider):
        """Without scene, prompt builder uses auto mode."""
        persona = _make_persona()
        result = await service.generate(persona=persona)

        assert "image_base64" in result
        mock_provider.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_passes_equipment_desc(self, service, mock_provider):
        """equipment_desc appears in the generated prompt."""
        persona = _make_persona()
        result = await service.generate(
            persona=persona,
            scene="castle",
            equipment_desc="wearing a silver armor",
        )
        assert "wearing a silver armor" in result["prompt"]

    @pytest.mark.asyncio
    async def test_generate_auto_fetches_equipment_desc(self, mock_provider):
        """Auto-fetches equipment_desc from equipment_service when not explicitly provided."""
        from unittest.mock import MagicMock

        from nous.domain.equipment.service import EquipmentService

        mock_eq_service = MagicMock(spec=EquipmentService)
        mock_eq_service.get_equipped_item_descs.return_value = MagicMock(
            is_ok=True,
            value=["wearing a silver armor", "a red scarf"],
        )

        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service()
            svc._equipment_service = mock_eq_service

            persona = _make_persona()
            result = await svc.generate(persona=persona, scene="castle")

        assert "wearing a silver armor" in result["prompt"]
        assert "a red scarf" in result["prompt"]

    @pytest.mark.asyncio
    async def test_generate_no_equipment_service_backward_compat(self, service, mock_provider):
        """No crash when equipment_service is None (backward compat)."""
        persona = _make_persona()
        result = await service.generate(persona=persona, scene="garden")
        assert "image_base64" in result
        # No equipment desc should appear
        assert "wearing" not in result["prompt"]

    @pytest.mark.asyncio
    async def test_generate_auto_fetch_empty_equipment(self, mock_provider):
        """No equipment_desc added when equipped items have no visual_desc."""
        from unittest.mock import MagicMock

        from nous.domain.equipment.service import EquipmentService

        mock_eq_service = MagicMock(spec=EquipmentService)
        mock_eq_service.get_equipped_item_descs.return_value = MagicMock(
            is_ok=True,
            value=[],
        )

        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service()
            svc._equipment_service = mock_eq_service

            persona = _make_persona()
            result = await svc.generate(persona=persona, scene="forest")

        assert "image_base64" in result
        # Prompt should not contain any extra equipment line
        assert result["prompt"] is not None


# ===========================================================================
# Tests: generate() — caching
# ===========================================================================


class TestGenerateCache:
    """Same prompt should hit cache within TTL."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_same_image(self, service, mock_provider):
        """Second call with identical prompt returns cached image."""
        persona = _make_persona()
        _r1 = await service.generate(persona=persona, scene="same")
        _r2 = await service.generate(persona=persona, scene="same")

        assert _r1["image_base64"] == _r2["image_base64"]
        # Provider should have been called only once
        assert mock_provider.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_miss_different_prompt(self, service, mock_provider):
        """Different prompts produce separate provider calls."""
        p1 = _make_persona(emotion="joy")
        p2 = _make_persona(emotion="anger")

        _r1 = await service.generate(persona=p1, scene="sunset")
        _r2 = await service.generate(persona=p2, scene="sunset")

        assert mock_provider.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry(self, mock_provider):
        """After TTL elapses, a new provider call is made."""
        with patch("nous.application.portrait.service.time") as mock_time:
            # Monotonic time starts at 0
            mock_time.monotonic.return_value = 0.0
            mock_time.monotonic.side_effect = None  # reset

            with patch(
                "nous.application.portrait.service.get_image_gen_provider",
                return_value=mock_provider,
            ):
                svc = _make_service()

            # Force TTL to a very small value for test
            svc._cache_ttl = 0.1  # 100ms

            persona = _make_persona()

            # First call — populate cache (monotonic = 0)
            await svc.generate(persona=persona, scene="expire_test")
            assert mock_provider.generate.await_count == 1

            # Second call — still within TTL (monotonic = 0.05)
            mock_time.monotonic.return_value = 0.05
            await svc.generate(persona=persona, scene="expire_test")
            assert mock_provider.generate.await_count == 1  # cache hit

            # Third call — TTL expired (monotonic = 0.2)
            mock_time.monotonic.return_value = 0.2
            await svc.generate(persona=persona, scene="expire_test")
            assert mock_provider.generate.await_count == 2  # cache miss


# ===========================================================================
# Tests: generate() — fallback
# ===========================================================================


class TestGenerateFallback:
    """Error / unavailable provider returns fallback with emoji."""

    @pytest.mark.asyncio
    async def test_fallback_when_provider_is_none(self):
        """No provider configured → fallback with error message."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=None,
        ):
            svc = _make_service()
            persona = _make_persona(emotion="sadness")
            result = await svc.generate(persona=persona)

            assert "error" in result
            assert result["fallback_emoji"] == "😢"

    @pytest.mark.asyncio
    async def test_fallback_when_provider_raises(self, mock_provider):
        """Provider exception → fallback."""
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("ComfyUI down"))

        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service()
            persona = _make_persona(emotion="anger")
            result = await svc.generate(persona=persona)

            assert "error" in result
            assert "Generation failed" in result["error"]
            assert result["fallback_emoji"] == "😠"

    @pytest.mark.asyncio
    async def test_fallback_when_provider_returns_empty(self, mock_provider):
        """Empty image list from provider → fallback."""
        mock_provider.generate = AsyncMock(return_value=[])

        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service()
            persona = _make_persona(emotion="fear")
            result = await svc.generate(persona=persona)

            assert "error" in result
            assert "Provider returned no images" in result["error"]
            assert result["fallback_emoji"] == "😨"

    @pytest.mark.asyncio
    async def test_fallback_unknown_emotion(self):
        """Unknown emotion falls back to neutral emoji."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=None,
        ):
            svc = _make_service()
            persona = _make_persona(emotion="nonexistent")
            result = await svc.generate(persona=persona)

            assert result["fallback_emoji"] == "😐"


# ===========================================================================
# Tests: budget enforcement
# ===========================================================================


class TestBudget:
    """Monthly budget check."""

    @pytest.mark.asyncio
    async def test_budget_blocks_generation(self, mock_provider):
        """When generate_count reaches max_monthly_budget, generation is blocked."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service(max_monthly_budget=2.0)

            persona = _make_persona()

            # First two calls should succeed
            r1 = await svc.generate(persona=persona)
            assert "error" not in r1

            r2 = await svc.generate(persona=persona, scene="different")
            assert "error" not in r2

            # Third call — blocked by budget
            r3 = await svc.generate(persona=persona, scene="another")
            assert "error" in r3
            assert "Monthly budget exceeded" in r3["error"]

    @pytest.mark.asyncio
    async def test_budget_zero_means_no_limit(self, mock_provider):
        """Budget = 0 means unlimited generation."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service(max_monthly_budget=0.0)

            persona = _make_persona()
            for _i in range(10):
                r = await svc.generate(persona=persona, scene=f"scene_{_i}")
                assert "error" not in r


# ===========================================================================
# Tests: should_auto_generate
# ===========================================================================


class TestShouldAutoGenerate:
    """Auto-generation gating logic."""

    @pytest.mark.asyncio
    async def test_auto_generate_returns_true_when_all_conditions_met(self, service):
        """All conditions pass → True."""
        persona = _make_persona(emotion_intensity=0.8)
        result = await service.should_auto_generate(persona)
        assert result is True

    @pytest.mark.asyncio
    async def test_auto_generate_disabled_when_config_off(self):
        """enabled=False → False."""
        svc = _make_service(enabled=False)
        persona = _make_persona(emotion_intensity=0.9)
        assert await svc.should_auto_generate(persona) is False

    @pytest.mark.asyncio
    async def test_auto_generate_disabled_when_auto_generate_off(self):
        """auto_generate=False → False."""
        svc = _make_service(auto_generate=False)
        persona = _make_persona(emotion_intensity=0.9)
        assert await svc.should_auto_generate(persona) is False

    @pytest.mark.asyncio
    async def test_auto_generate_below_threshold(self, service):
        """emotion_intensity < threshold → False."""
        persona = _make_persona(emotion_intensity=0.1)
        assert await service.should_auto_generate(persona) is False

    @pytest.mark.asyncio
    async def test_auto_generate_respects_interval(self, service, mock_provider):
        """Calling generate resets interval → should_auto_generate is False."""
        persona = _make_persona(emotion_intensity=0.8)
        await service.generate(persona=persona, scene="test")
        assert await service.should_auto_generate(persona) is False

    @pytest.mark.asyncio
    async def test_auto_generate_budget_exceeded(self, mock_provider):
        """Budget exhausted → False."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service(max_monthly_budget=1.0)

            persona = _make_persona(emotion_intensity=0.8)
            await svc.generate(persona=persona, scene="use_budget")
            assert await svc.should_auto_generate(persona) is False


# ===========================================================================
# Tests: health_check
# ===========================================================================


class TestHealthCheck:
    """Provider health check delegation."""

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, service):
        """When provider health_check returns True."""
        assert await service.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_no_provider(self):
        """No provider → False."""
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=None,
        ):
            svc = _make_service()
            assert await svc.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_provider_no_method(self, mock_provider):
        """Provider lacks health_check → False."""
        del mock_provider.health_check
        with patch(
            "nous.application.portrait.service.get_image_gen_provider",
            return_value=mock_provider,
        ):
            svc = _make_service()
            assert await svc.health_check() is False


# ===========================================================================
# Tests: auto prompt builder
# ===========================================================================


class TestAutoPrompt:
    """Tests for the auto-prompt builder (no LLM scene)."""

    def test_auto_prompt_intensity_high(self):
        """emotion_intensity 0.9 → 'intense' modifier in prompt."""
        persona = _make_persona(emotion_intensity=0.9)
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        assert "intense" in prompt

    def test_auto_prompt_intensity_low(self):
        """emotion_intensity 0.2 → 'subtle' modifier in prompt."""
        persona = _make_persona(emotion_intensity=0.2)
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        assert "subtle" in prompt

    def test_auto_prompt_intensity_medium(self):
        """emotion_intensity 0.5 → no modifier in prompt."""
        persona = _make_persona(emotion_intensity=0.5)
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        assert "intense" not in prompt
        assert "subtle" not in prompt

    def test_auto_prompt_with_full_state(self):
        """All personality state fields reflected in prompt."""
        persona = _make_persona(
            emotion_intensity=0.9,
            mental_state="focused and determined",
            physical_state="sweating lightly",
            environment="dark forest at night",
        )
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        assert "intense" in prompt
        assert "focused and determined" in prompt
        assert "sweating lightly" in prompt
        assert "dark forest at night" in prompt
        assert "detailed background" in prompt

    def test_auto_prompt_environment_none(self):
        """When environment is None → 'simple background' is present."""
        persona = _make_persona(environment=None)
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        assert "simple background" in prompt

    def test_auto_prompt_mental_state_none(self):
        """When mental_state is None → nothing extra added from it."""
        persona = _make_persona(mental_state=None, emotion_intensity=0.5)
        prompt, _neg = PortraitPromptBuilder.build(persona=persona)
        # No mental state string in prompt
        assert "simple background" in prompt
        # Should still have normal structure
        assert "1girl" in prompt
        assert "test_char" in prompt


class TestIntensityModifier:
    """Unit tests for _intensity_modifier helper."""

    def test_intensity_below_03(self):
        assert _intensity_modifier(0.0) == "subtle"
        assert _intensity_modifier(0.29) == "subtle"

    def test_intensity_03_to_07(self):
        assert _intensity_modifier(0.3) == ""
        assert _intensity_modifier(0.5) == ""
        assert _intensity_modifier(0.7) == ""

    def test_intensity_above_07(self):
        assert _intensity_modifier(0.71) == "intense"
        assert _intensity_modifier(1.0) == "intense"


# ===========================================================================
# Tests: emotion emoji mapping
# ===========================================================================


class TestEmotionEmoji:
    """EMOTION_EMOJI mapping completeness."""

    def test_all_defined_emotions_have_emoji(self):
        """Every known emotion in PortraitPromptBuilder has an emoji."""
        from nous.domain.persona.portrait_prompt import _EMOTION_ADJECTIVES
        from nous.domain.value_objects import EMOTION_EMOJI

        for emotion in _EMOTION_ADJECTIVES:
            assert emotion in EMOTION_EMOJI, f"Missing emoji for {emotion!r}"
            assert EMOTION_EMOJI[emotion] != ""
