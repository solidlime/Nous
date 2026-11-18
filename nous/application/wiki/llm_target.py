"""wiki の LLM 接続先の解決（kanban #66）。

``WikiConfig`` は ``openrouter`` 既定・鍵なし。実環境ではチャット設定
（チャットタブが書く ``config.json``）にしか鍵が無いため、編纂が毎サイクル
``wiki LLM api_key is not configured`` で落ちていた。

解決順:

1. ``WikiConfig`` に鍵がある（``NOUS_WIKI__API_KEY`` 等の明示設定）→ wiki 専用設定
2. ペルソナのチャット設定に鍵がある → そのプロバイダ/モデル/接続先を流用
3. どちらも無い → 空の鍵（呼び出し側が失敗として扱う）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nous.config.settings import Settings, WikiConfig


def resolve_llm(cfg: WikiConfig, settings: Settings, chat: Any = None) -> tuple[str, str, str, str]:
    """wiki 用の ``(provider, model, api_key, base_url)`` を返す。"""
    api_key = cfg.get_effective_api_key(settings)
    if api_key:
        return cfg.provider, cfg.model, api_key, cfg.base_url
    if chat is not None and getattr(chat, "api_key", None):
        return chat.provider, getattr(chat, "model", "") or cfg.model, chat.api_key, getattr(chat, "base_url", "") or ""
    return cfg.provider, cfg.model, "", cfg.base_url
