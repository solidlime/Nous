"""LLM接続設定 — ProviderConfig.

ChatConfig から分割された、LLMプロバイダ接続に関する設定を保持する。
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator

from nous.config.runtime_config import RuntimeConfigManager

# Backward-compat env var names for API keys per provider (legacy, without NOUS_ prefix)
_ENV_API_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GEMINI_API_KEY",
    "opencode_go": "OPENCODE_GO_API_KEY",
}

# Default model names per provider
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-5",
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o",
    "google": "gemini-2.5-flash",
    "opencode_go": "deepseek-v4-pro",
}

# Default base URLs per provider (empty means use SDK default)
_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "",
    "openai": "",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "",
    "opencode_go": "",
}

# Allowed reasoning effort levels (shared across providers, converted per provider)
REASONING_EFFORTS = frozenset({"low", "medium", "high", "max"})


class ProviderConfig(BaseModel):
    """LLMプロバイダ接続設定。"""

    provider: str = Field(default="anthropic", description="使用するLLMプロバイダー（anthropic / openai / openrouter など）。")
    model: str = Field(default="", description="使用するモデル名。空欄ならプロバイダーの既定モデルを使います。")
    api_key: str | None = Field(default=None, description="LLM APIの認証キー。")
    base_url: str = Field(default="", description="APIの接続先URL。カスタムエンドポイント利用時に設定します。")
    temperature: float = Field(default=0.7, description="応答の創造性（0〜2）。高いほど多様、低いほど安定します。")
    max_tokens: int = Field(default=8192, description="1回の応答で生成する最大トークン数。")
    max_tool_calls: int = Field(default=5, description="1ターンで実行できるツール呼び出しの最大回数。")
    auto_extract: bool = Field(default=True, description="会話から重要な記憶を自動抽出します。")
    extract_model: str = Field(default="", description="記憶抽出に使うモデル。空欄ならメインのモデルを使います。")
    extract_max_tokens: int = Field(default=512, description="記憶抽出時の最大トークン数。")
    tool_result_max_chars: int = Field(default=4000, description="ツール実行結果を表示・保持する最大文字数。")
    dynamic_temperature: bool = Field(default=True, description="感情に応じてTemperatureを動的に調整します。")
    emotion_temperature_scale: float = Field(default=0.2, description="動的温度調整の強さ（0〜1）。")
    top_p: float | None = Field(default=None, description="サンプリングの累積確率。空欄で無効。")
    reasoning_enabled: bool = Field(default=False, description="推論（thinking）を有効にします。")
    reasoning_effort: str = Field(default="medium", description="推論の深さ（low / medium / high / max）。")

    @field_validator("temperature")
    @classmethod
    def _clamp_temperature(cls, v: float) -> float:
        # 小数点2桁に丸めてからクランプ（プロバイダが3桁以上を拒否するため）
        return max(0.0, min(2.0, round(v, 2)))

    @field_validator("max_tokens")
    @classmethod
    def _clamp_max_tokens(cls, v: int) -> int:
        return max(1, min(32768, v))

    @field_validator("max_tool_calls")
    @classmethod
    def _clamp_tool_calls(cls, v: int) -> int:
        return max(0, min(20, v))

    @field_validator("extract_max_tokens")
    @classmethod
    def _clamp_extract_max_tokens(cls, v: int) -> int:
        return max(64, min(2048, v))

    @field_validator("tool_result_max_chars")
    @classmethod
    def _clamp_tool_result_max_chars(cls, v: int) -> int:
        return max(500, min(100000, v))

    @field_validator("emotion_temperature_scale")
    @classmethod
    def _clamp_emotion_temperature_scale(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("top_p")
    @classmethod
    def _clamp_top_p(cls, v: float | None) -> float | None:
        if v is None:
            return None
        # 小数点2桁に丸めてからクランプ（_clamp_temperature と同規約）
        return max(0.0, min(1.0, round(v, 2)))

    @field_validator("reasoning_effort")
    @classmethod
    def _validate_reasoning_effort(cls, v: str) -> str:
        if v in REASONING_EFFORTS:
            return v
        return "medium"  # 不正値は既定へ clamp（設定全体のデフォルトフォールバック防止）

    def get_effective_api_key(self) -> str:
        """Return stored API key or fall back via RuntimeConfigManager.

        If api_key is explicitly set (even to empty string), return it as-is
        and do NOT fall through to environment variables or RuntimeConfigManager.
        """
        if self.api_key is not None:
            return self.api_key
        # RuntimeConfigManager (reads NOUS_ANTHROPIC_API_KEY etc.)
        key_name = f"{self.provider}_api_key"
        value, _ = RuntimeConfigManager().get_effective_value("api_keys", key_name)
        if value:
            return value
        # Backward compat: old env vars without NOUS_ prefix
        env_var = _ENV_API_KEYS.get(self.provider, "")
        return os.environ.get(env_var, "")

    def get_effective_model(self) -> str:
        """Return stored model name or default for the provider."""
        if self.model:
            return self.model
        return _DEFAULT_MODELS.get(self.provider, "")

    def get_effective_base_url(self) -> str:
        """Return stored base URL or provider default."""
        if self.base_url:
            return self.base_url
        return _DEFAULT_BASE_URLS.get(self.provider, "")

    def is_configured(self) -> bool:
        """Return True if provider has an API key available."""
        return bool(self.get_effective_api_key())

    def to_safe_dict(self) -> dict:
        """Return config as dict with API key masked."""
        d = self.model_dump()
        raw_key = d.get("api_key", "")
        if raw_key:
            visible = raw_key[:4] if len(raw_key) > 4 else ""
            d["api_key"] = visible + "****"
        d["is_configured"] = self.is_configured()
        d["effective_model"] = self.get_effective_model()
        d["effective_base_url"] = self.get_effective_base_url()
        return d
