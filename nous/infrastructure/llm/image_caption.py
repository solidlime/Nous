"""Image captioner for non-vision LLM models.

When a provider does not support vision (supports_vision() == False),
this module generates a text description of images using a vision-capable
model or a dedicated captioning model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.tool_config import ToolConfig
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class ImageCaptioner:
    """Generates text captions for images using a vision-capable LLM.

    Usage:
        captioner = ImageCaptioner(config=tool_config)
        caption = await captioner.caption(base64_data, mime_type="image/png")
    """

    def __init__(
        self,
        config: ToolConfig | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        self._config = config
        self._provider = provider

    def _get_or_create_provider(self) -> LLMProvider | None:
        """Return the injected provider or create one from config."""
        if self._provider is not None:
            return self._provider
        if self._config is None:
            return None
        if not self._config.image_caption_enabled:
            return None

        from nous.infrastructure.llm.factory import get_provider

        api_key = self._config.image_caption_api_key or self._get_global_api_key()
        if not api_key:
            logger.warning("ImageCaptioner: no API key configured for caption provider")
            return None

        try:
            provider = get_provider(
                provider=self._config.image_caption_provider,
                api_key=api_key,
                model=self._config.image_caption_model,
                base_url=self._config.image_caption_base_url,
            )
        except Exception:
            logger.warning("ImageCaptioner: failed to create provider", exc_info=True)
            return None
        return provider

    def _get_global_api_key(self) -> str:
        """Fallback to the main API key from config (ChatConfig facade)."""
        # If the config is a ToolConfig nested inside ChatConfig, access the api_key
        # from the parent ChatConfig via the ToolConfig's own api_key attribute.
        # ToolConfig doesn't have api_key directly, but ChatConfig proxies it.
        # We try to access via the config object directly.
        return ""

    async def caption(
        self,
        base64_data: str,
        mime_type: str = "image/png",
        hint: str = "",
    ) -> str:
        """Generate a text caption for a single image.

        Args:
            base64_data: Raw base64-encoded image data (no data: URL prefix).
            mime_type: MIME type of the image (e.g. "image/png", "image/jpeg").
            hint: Optional hint to guide the caption description.

        Returns:
            Caption text, or empty string on failure.
        """
        provider = self._get_or_create_provider()
        if provider is None:
            return ""

        return await self._caption_with_provider(provider, base64_data, mime_type, hint)

    async def _caption_with_provider(
        self,
        provider: LLMProvider,
        base64_data: str,
        mime_type: str,
        hint: str = "",
    ) -> str:
        """Internal: call a vision-capable provider to caption an image."""
        if not base64_data:
            return ""

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent

        system_prompt = "You are an image captioning assistant. Describe images concisely."
        user_prompt = "Describe this image in 1-2 sentences. Focus on what is visually present."
        if hint:
            user_prompt = f"{user_prompt} {hint}"

        content_parts: list[dict] = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_data}",
                    "detail": "low",
                },
            },
        ]
        messages = [
            LLMMessage(role="user", content=user_prompt, content_parts=content_parts),
        ]

        full_text = ""
        try:
            async for event in provider.stream(
                messages=messages,
                system=system_prompt,
                temperature=0.3,
                max_tokens=256,
            ):
                if isinstance(event, TextDeltaEvent):
                    full_text += event.content
                elif isinstance(event, ErrorEvent):
                    logger.warning("ImageCaptioner: provider error: %s", event.message)
                    return ""
                elif isinstance(event, DoneEvent):
                    break
        except Exception:
            logger.warning("ImageCaptioner: exception during caption generation", exc_info=True)
            return ""

        return full_text.strip()

    async def caption_batch(
        self,
        images: list[dict],
        hint: str = "",
    ) -> list[str]:
        """Generate captions for multiple images.

        Args:
            images: List of dicts with keys "base64_data" and "mime_type".
            hint: Optional hint to guide caption descriptions.

        Returns:
            List of caption strings (empty string for failed images).
        """
        if not images:
            return []

        import asyncio

        tasks = [
            self.caption(
                base64_data=img.get("base64_data", ""),
                mime_type=img.get("mime_type", "image/png"),
                hint=hint,
            )
            for img in images
        ]
        return list(await asyncio.gather(*tasks))
