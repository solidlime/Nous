"""Health check module for ComfyUI connection."""

from __future__ import annotations

import httpx


class ImageGenHealthChecker:
    """Periodic health check for ComfyUI availability with fallback detection."""

    def __init__(self, comfyui_url: str) -> None:
        self.comfyui_url = comfyui_url.rstrip("/")
        self._last_status: bool | None = None

    async def check(self) -> bool:
        """Check if ComfyUI is reachable. Caches result for 10 seconds."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.comfyui_url}/system_stats")
                self._last_status = r.status_code == 200
                return self._last_status
        except Exception:
            self._last_status = False
            return False

    @property
    def is_available(self) -> bool:
        """Returns last known status without making a request."""
        return self._last_status is True

    def get_fallback_message(self) -> str:
        """Get a message explaining the fallback state."""
        if self._last_status is False:
            return "ComfyUI is unreachable — using emotion icon fallback"
        return ""
