"""PortraitGenerationService — application service for persona portrait generation.

Orchestrates prompt building → image generation → caching → fallback.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

from nous.application.event_bus import (
    PORTRAIT_GENERATE_COMPLETE,
    PORTRAIT_GENERATE_ERROR,
    PORTRAIT_GENERATE_START,
)
from nous.domain.persona.body_state import extract_body_metrics
from nous.domain.persona.portrait_prompt import PortraitPromptBuilder
from nous.domain.value_objects import EMOTION_EMOJI
from nous.infrastructure.image_gen.base import ImageGenConfig
from nous.infrastructure.image_gen.factory import get_image_gen_provider

if TYPE_CHECKING:
    from nous.application.event_bus import EventBus
    from nous.config.settings import PortraitGenerationConfig
    from nous.domain.persona.entities import PersonaState
    from nous.infrastructure.image_gen.base import GeneratedImage


class PortraitGenerationService:
    """Application service for generating character portraits.

    Responsibilities:
    - Build prompts via PortraitPromptBuilder (LLM scene or auto).
    - Dispatch to the image generation provider (ComfyUI / DALL-E / Stability).
    - Cache identical prompts for 5 minutes.
    - Fall back to emotion emoji when provider is unavailable or fails.
    - Enforce monthly budget cap for cloud providers.
    """

    def __init__(self, config: PortraitGenerationConfig, event_bus: EventBus | None = None) -> None:
        self._config = config
        self._event_bus = event_bus

        # Convert PortraitGenerationConfig → ImageGenConfig so the factory
        # can build the right provider.
        gen_cfg = ImageGenConfig(
            provider=config.provider,
            comfyui_url=config.comfyui_url or "http://localhost:8188",
        )
        self._provider = get_image_gen_provider(gen_cfg)

        # Cache: {prompt_hash: (base64, monotonic_timestamp)}
        self._cache: dict[str, tuple[str, float]] = {}
        self._cache_ttl: float = 300.0  # 5 minutes

        # Budget / rate counters
        self._generate_count: int = 0
        # Sentinel: None means "never generated" → interval check is skipped.
        # Using 0.0 here is a bug because time.monotonic() - 0.0 is always
        # a large value (system uptime) on long-running hosts but can be
        # small on freshly-booted CI runners, making the interval check
        # time-dependent and flaky.
        self._last_generate_time: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        persona: PersonaState,
        scene: str | None = None,
        equipment_desc: str | None = None,
    ) -> dict:
        """Generate a portrait for the given persona state.

        Parameters
        ----------
        persona : PersonaState
            Current persona state (emotion, appearance, body fields).
        scene : str | None
            Optional LLM-provided scene description.  When provided the
            prompt builder uses LLM synthesis; otherwise auto synthesis.
        equipment_desc : str | None
            Optional equipment / clothing description.

        Returns
        -------
        dict
            On success: ``{"image_base64": str, "prompt": str,
            "negative_prompt": str}``.
            On failure: ``{"error": str, "fallback_emoji": str}``.
        """
        # ── 1. Build prompt ────────────────────────────────────────────
        body_state = extract_body_metrics(persona)
        prompt, negative_prompt = PortraitPromptBuilder.build(
            persona=persona,
            scene=scene,
            equipment_desc=equipment_desc,
            body_state=body_state,
        )

        # ── 2. Publish start event ─────────────────────────────────────
        if self._event_bus is not None:
            await self._event_bus.publish(
                PORTRAIT_GENERATE_START,
                {
                    "persona": persona.persona,
                    "emotion": persona.emotion,
                    "scene": scene,
                    "prompt": prompt,
                },
            )

        # ── 3. Check cache ─────────────────────────────────────────────
        cache_key = hashlib.md5(prompt.encode()).hexdigest()
        cached = self._cache.get(cache_key)
        if cached is not None:
            cached_b64, cached_ts = cached
            if time.monotonic() - cached_ts < self._cache_ttl:
                result = {
                    "image_base64": cached_b64,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                }
                if self._event_bus is not None:
                    await self._event_bus.publish(
                        PORTRAIT_GENERATE_COMPLETE,
                        {
                            "persona": persona.persona,
                            "emotion": persona.emotion,
                            "image_base64": result["image_base64"],
                            "cached": True,
                        },
                    )
                return result

        # ── 4. Budget gate ─────────────────────────────────────────────
        if self._config.max_monthly_budget > 0 and self._generate_count >= int(self._config.max_monthly_budget):
            return await self._publish_error(persona, "Monthly budget exceeded")

        # ── 5. Provider check & generate ───────────────────────────────
        if self._provider is None:
            return await self._publish_error(persona, "No image provider configured")

        try:
            images: list[GeneratedImage] = await self._provider.generate(
                prompt=prompt,
                size=self._config.size,
                quality=self._config.quality,
            )
            if not images:
                return await self._publish_error(persona, "Provider returned no images")

            image_b64 = images[0].base64
        except Exception as exc:
            return await self._publish_error(persona, f"Generation failed: {exc}")

        # ── 6. Update cache & counters ─────────────────────────────────
        self._cache[cache_key] = (image_b64, time.monotonic())
        self._generate_count += 1
        self._last_generate_time = time.monotonic()

        result = {
            "image_base64": image_b64,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
        }

        # ── 7. Publish complete event ──────────────────────────────────
        if self._event_bus is not None:
            await self._event_bus.publish(
                PORTRAIT_GENERATE_COMPLETE,
                {
                    "persona": persona.persona,
                    "emotion": persona.emotion,
                    "image_base64": result["image_base64"],
                    "cached": False,
                },
            )

        return result

    async def should_auto_generate(self, persona: PersonaState) -> bool:
        """Check whether auto-generation should trigger for this state.

        Returns ``True`` only when **all** conditions are met:

        * ``config.enabled`` and ``config.auto_generate`` are both ``True``.
        * ``persona.emotion_intensity >= config.emotion_threshold``.
        * Minimum generation interval (``generate_interval_min``) has elapsed.
        * Monthly budget has not been exhausted (if budget is set).
        """
        if not self._config.enabled or not self._config.auto_generate:
            return False

        if persona.emotion_intensity < self._config.emotion_threshold:
            return False

        if self._last_generate_time is not None:
            elapsed = time.monotonic() - self._last_generate_time
            if elapsed < self._config.generate_interval_min * 60:
                return False

        return not (
            self._config.max_monthly_budget > 0 and self._generate_count >= int(self._config.max_monthly_budget)
        )

    async def health_check(self) -> bool:
        """Check whether the image generation backend is reachable.

        Delegates to the provider's ``health_check()`` method if available,
        otherwise returns ``False``.
        """
        if self._provider is None:
            return False

        health = getattr(self._provider, "health_check", None)
        if health is None:
            return False

        try:
            result = await health()
            return bool(result)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _publish_error(self, persona: PersonaState, error: str) -> dict:
        """Publish an error event and return the fallback response dict."""
        if self._event_bus is not None:
            await self._event_bus.publish(
                PORTRAIT_GENERATE_ERROR,
                {
                    "persona": persona.persona,
                    "emotion": persona.emotion,
                    "error": error,
                },
            )
        return {
            "error": error,
            "fallback_emoji": EMOTION_EMOJI.get(persona.emotion, "😐"),
        }
