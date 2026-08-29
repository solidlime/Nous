from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .openai_compat import OpenAICompatProvider

# 旧 provider 名 → OpenAI互換デフォルト base_url（移行マップ）。
# provider 選択は廃止済み。全接続は OpenAICompatProvider に統一され、
# このマップは旧 config.json の provider フィールドから base_url を復元するためにのみ使う。
_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com/v1/",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "opencode_go": "https://opencode.ai/zen/go/v1",
}


def get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> OpenAICompatProvider:
    """常に OpenAICompatProvider を返す（シグネチャ互換維持・18 call sites）。

    base_url が空の場合、旧 provider 名に応じた互換エンドポイントをデフォルト解決する。
    """
    from .openai_compat import OpenAICompatProvider

    resolved_base_url = base_url or _DEFAULT_BASE_URLS.get(provider, "")
    return OpenAICompatProvider(api_key=api_key, model=model, base_url=resolved_base_url)
