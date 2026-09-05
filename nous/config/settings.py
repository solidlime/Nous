from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""

    model: str = "onnx-community/ruri-v3-30m-ONNX"
    device: str = "cpu"
    batch_size: int = 32


class RerankerConfig(BaseModel):
    """Reranker model configuration."""

    model: str = "hotchpotch/japanese-reranker-xsmall-v2"
    enabled: bool = True


class QdrantConfig(BaseModel):
    """Qdrant vector store configuration."""

    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_prefix: str = "memory_"


class ServerConfig(BaseModel):
    """HTTP/MCP server configuration."""

    host: str = "0.0.0.0"  # nosec B104 - intentional for Docker deployment; use 127.0.0.1 for localhost-only
    port: int = 26262


class ForgettingConfig(BaseModel):
    """FSRS v6 forgetting curve configuration."""

    enabled: bool = True
    decay_interval_seconds: int = 3600
    min_strength: float = 0.005
    emotion_half_life_hours: float = 24.0
    """Base half-life for emotion decay. Effective half-life = base * max(0.3, intensity)."""


class MemoryEnrichmentConfig(BaseModel):
    """Memory enrichment (importance + relations) via LLM."""

    enabled: bool = True
    provider: str = "openrouter"
    api_key: str | None = None
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"
    min_chars: int = 10  # skip enrichment for very short memories

    def get_effective_api_key(self, settings: Settings) -> str:
        """Return API key, falling back to global Settings keys."""
        # 1. Explicit memory_enrichment.api_key
        if self.api_key:
            return self.api_key

        # 2. Provider-matched global Settings key
        if self.provider == "openrouter" and settings.openrouter_api_key:
            return settings.openrouter_api_key
        if self.provider == "anthropic" and settings.anthropic_api_key:
            return settings.anthropic_api_key
        if self.provider == "openai" and settings.openai_api_key:
            return settings.openai_api_key
        if self.provider == "google" and settings.google_api_key:
            return settings.google_api_key
        if self.provider == "opencode_go" and settings.opencode_go_api_key:
            return settings.opencode_go_api_key

        # 3. RuntimeConfigManager fallback (hot-reload overrides)
        from nous.config.runtime_config import RuntimeConfigManager

        key_name = f"{self.provider}_api_key"
        value, _ = RuntimeConfigManager().get_effective_value("api_keys", key_name)
        if value:
            return value

        # 4. Backward compat: legacy env vars without NOUS_ prefix
        _legacy_env_keys = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GEMINI_API_KEY",
            "opencode_go": "OPENCODE_GO_API_KEY",
        }
        env_var = _legacy_env_keys.get(self.provider, "")
        return os.environ.get(env_var, "")


class AutoCaptureConfig(BaseModel):
    """Auto-capture: extract key information from session as memories."""

    enabled: bool = False
    """Auto-capture memories at end of each chat turn."""

    max_memories: int = 5
    """Maximum memories to create per session."""


class IrodoriAdvancedParams(BaseModel):
    """Irodori-TTS extra_body.irodori advanced parameters."""

    num_steps: int = 30
    """Inference steps. Range: 10-50. Higher = better quality, slower."""

    cfg_scale_text: float = 3.2
    """Text adherence. Range: 1.0-5.0."""

    cfg_scale_speaker: float = 5.0
    """Reference voice fidelity. Range: 1.0-8.0."""

    cfg_scale_caption: float = 4.2
    """Emotion/style strength. Range: 1.0-8.0."""

    chunk_min_chars: int = 85
    """Min chars per chunk for long text. Range: 30-200."""

    seed: int | None = None
    """Random seed. None = random. Set to int for deterministic output."""


class IrodoriConfig(BaseModel):
    """Irodori-TTS connection configuration — provider settings only.
    Env var: ``NOUS_IRODORI__URL`` (default: http://localhost:8088)
    """

    url: str = "http://localhost:8088"
    """Irodori-TTS-Server base URL (e.g. http://192.168.50.150:8088). /v1 prefix is added automatically."""

    voice: str = "default"
    """Default voice name."""

    model: str = "irodori-tts"
    """TTS model name (fixed for Irodori)."""

    timeout_seconds: int = 30
    """Generation timeout in seconds."""

    advanced: IrodoriAdvancedParams = IrodoriAdvancedParams()


class CorsConfig(BaseModel):
    """CORS (Cross-Origin Resource Sharing) configuration."""

    allowed_origins: list[str] = ["*"]
    """Allowed origins. Env var ``NOUS_CORS__ALLOWED_ORIGINS`` accepts JSON array
    (e.g. ``'["http://a.com","http://b.com"]'``) **or** comma-separated string
    (e.g. ``http://a.com,http://b.com``).
    Default: ``["*"]`` (development only). Production should set explicit origins."""

    allow_credentials: bool = True
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_comma_separated(cls, v: object) -> object:
        """Allow comma-separated string as input (for non-JSON env vars)."""
        if isinstance(v, str):
            # Try JSON first
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                pass
            # Fallback: comma-separated
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @model_validator(mode="after")
    def _enforce_credentials_compatibility(self) -> Self:
        """ワイルドカード origins × allow_credentials=True はブラウザに拒否されるため強制無効化する。"""
        if "*" in self.allowed_origins and self.allow_credentials:
            import logging

            logging.getLogger(__name__).warning(
                "CORS: allowed_origins contains '*' with allow_credentials=True — "
                "browsers reject this combination. Forcing allow_credentials=False."
            )
            self.allow_credentials = False
        return self


class PluginConfig(BaseModel):
    """Plugin API configuration — default OFF for security.

    Must be explicitly enabled AND configured with an api_key for access.
    """

    enabled: bool = False
    """DEFAULT OFF — must be explicitly enabled for plugin API access.
    Set ``NOUS_PLUGIN__ENABLED=true`` to enable."""

    api_key: str = ""
    """API key required for Bearer token authentication.
    Must be a non-empty string when enabled.
    Set ``NOUS_PLUGIN__API_KEY=<strong_key>``."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="NOUS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: ServerConfig = ServerConfig()
    plugin: PluginConfig = Field(default_factory=PluginConfig)
    # LLM provider API keys (shared across subsystems)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    google_api_key: str = ""  # env: NOUS_GOOGLE_API_KEY
    opencode_go_api_key: str = ""  # env: NOUS_OPENCODE_GO_API_KEY

    embedding: EmbeddingConfig = EmbeddingConfig()
    reranker: RerankerConfig = RerankerConfig()
    qdrant: QdrantConfig = QdrantConfig()
    forgetting: ForgettingConfig = ForgettingConfig()
    memory_enrichment: MemoryEnrichmentConfig = MemoryEnrichmentConfig()
    auto_capture: AutoCaptureConfig = AutoCaptureConfig()
    cors: CorsConfig = CorsConfig()
    irodori: IrodoriConfig = Field(default_factory=IrodoriConfig)
    timezone: str = "Asia/Tokyo"
    data_root: str = "./data"
    log_level: str = "INFO"
    default_persona: str | None = None
    contradiction_threshold: float = 0.85
    duplicate_threshold: float = 0.90

    # Flat CORS origins env var (supports comma-separated; nested var
    # NOUS_CORS__ALLOWED_ORIGINS requires JSON array).  Parsed into
    # ``cors.allowed_origins`` via :meth:`_apply_cors_allowed_origins`.
    cors_allowed_origins_env: str = Field(
        default="",
        alias="NOUS_CORS_ALLOWED_ORIGINS",
    )

    @model_validator(mode="after")
    def apply_cors_allowed_origins(self) -> Self:
        """Parse NOUS_CORS_ALLOWED_ORIGINS (comma-separated) into cors.allowed_origins."""
        raw = self.cors_allowed_origins_env.strip()
        if raw:
            import json

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [s.strip() for s in raw.split(",") if s.strip()]
            if isinstance(parsed, str):
                parsed = [parsed]
            self.cors.allowed_origins = parsed
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        from zoneinfo import available_timezones

        if v not in available_timezones():
            raise ValueError(f"Invalid timezone: '{v}'. Use a valid IANA timezone (e.g., 'Asia/Tokyo').")
        return v

    @field_validator("contradiction_threshold", "duplicate_threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Threshold must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return upper

    @computed_field
    @property
    def data_dir(self) -> str:
        """DEPRECATED: Use persona_dir or persona_path() instead. 旧互換用。"""
        return f"{self.data_root}/persona"

    @computed_field
    @property
    def persona_dir(self) -> str:
        """ペルソナ別データ格納ディレクトリ: {data_root}/persona"""
        return f"{self.data_root}/persona"

    def persona_path(self, persona_name: str) -> str:
        """特定ペルソナのデータディレクトリパス: {data_root}/persona/{name}"""
        return f"{self.persona_dir}/{persona_name}"

    @computed_field
    @property
    def import_dir(self) -> str:
        """Auto-Import ZIP配置ディレクトリ: {data_root}/import"""
        return f"{self.data_root}/import"

    @computed_field
    @property
    def cache_dir(self) -> str:
        """モデルキャッシュディレクトリ: {data_root}/cache"""
        return f"{self.data_root}/cache"

    @computed_field
    @property
    def config_dir(self) -> str:
        """設定ファイルディレクトリ: {data_root}/config"""
        return f"{self.data_root}/config"

    @computed_field
    @property
    def skills_dir(self) -> str:
        """Skillsファイルディレクトリ（data_root内）"""
        return f"{self.data_root}/skills"

    def ensure_directories(self) -> None:
        """起動時に必要なディレクトリを全て作成する。"""
        dirs = [
            self.persona_dir,
            self.import_dir,
            Path(self.import_dir) / "done",
            self.cache_dir,
            Path(self.cache_dir) / "huggingface",
            self.config_dir,
            self.skills_dir,
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton (thread-safe via lru_cache)."""
    return Settings()
