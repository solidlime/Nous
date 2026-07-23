from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class GeminiProvider(OpenAICompatProvider):
    """Google Gemini provider via OpenAI-compatible endpoint.

    Gemini は OpenAI 互換エンドポイント ``/v1beta/openai/chat/completions`` を提供している。
    ツール呼び出し、ストリーミング、システムプロンプトすべて OpenAI 形式でOK。
    """

    def __init__(self, api_key: str, model: str, base_url: str = "") -> None:
        super().__init__(
            api_key=api_key,
            model=model or "gemini-2.5-flash",
            base_url=base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
