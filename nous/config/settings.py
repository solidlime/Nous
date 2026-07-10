from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""

    model: str = "cl-nagoya/ruri-v3-30m"
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


class MemoRAGConfig(BaseModel):
    """MemoRAG-inspired memory context snapshot and clue generation configuration."""

    enabled: bool = True
    """Enable MemoryContextSnapshot building (LLM-free, always safe to enable)."""

    clue_generation_enabled: bool = False
    """Enable LLM-based clue generation for memorag search mode (requires ChatConfig LLM)."""

    rebuild_threshold: int = 20
    """Rebuild snapshot when memory count increases by this many since last build."""

    snapshot_top_memories: int = 20
    """Number of top-importance memories to include in the snapshot."""

    snapshot_interval_hours: float = 1.0
    """Minimum hours between automatic snapshot rebuilds."""


class SandboxConfig(BaseModel):
    """Sandbox code execution configuration."""

    enabled: bool = True
    provider: str = "docker"  # "docker" | "none"
    image: str = "nous-sandbox:latest"  # custom sandbox image
    docker_host: str = ""  # empty = auto-detect socket, "tcp://host:2375" = remote Docker
    docker_sock: str = ""  # override socket path (empty = auto-detect common paths)
    timeout: int = 30
    session_idle_timeout: int = 1800
    allowed_languages: list[str] = ["python", "javascript", "bash", "go", "rust"]
    max_sessions: int = 10
    workspace_dir: str = "/sandbox"
    host_data_root: str = ""  # HOST-absolute path to data dir (needed for sibling-container volume mounts)


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


class AutoCaptureConfig(BaseModel):
    """Auto-capture: extract key information from session as memories."""

    enabled: bool = False
    """Auto-capture memories at end of each chat turn."""

    max_memories: int = 5
    """Maximum memories to create per session."""


class IrodoriConfig(BaseModel):
    """Irodori-TTS connection configuration."""

    enabled: bool = False
    """Default OFF — must be explicitly enabled."""

    url: str = "http://localhost:8088/v1"
    """Irodori-TTS-Server OpenAI-compatible API endpoint."""

    voice: str = "default"
    """Default voice name."""

    timeout_seconds: int = 30
    """Generation timeout in seconds."""


class PortraitGenerationConfig(BaseModel):
    """Portrait generation configuration — CRITICAL cost-control layer (default OFF)."""

    enabled: bool = False
    """DEFAULT OFF — must be explicitly enabled for any portrait generation."""

    provider: str = "comfyui"
    """"comfyui" | "openai" | "stability" — generation backend."""

    comfyui_url: str = "http://localhost:8188"
    """ComfyUI API address (used when provider="comfyui")."""

    auto_generate: bool = False
    """Auto-generate portrait on emotion change (also default OFF)."""

    generate_interval_min: int = 10
    """Minimum minutes between automatic generations."""

    size: str = "512x512"
    """Preview size."""

    quality: str = "standard"

    emotion_threshold: float = 0.3
    """Only regenerate if emotion intensity change exceeds this threshold."""

    max_monthly_budget: float = 5.0
    """Monthly USD cap for cloud providers (0 = N/A for local ComfyUI)."""

    healthcheck_enabled: bool = True
    """Periodically check if ComfyUI is reachable."""

    healthcheck_interval_seconds: int = 60
    """Interval between health checks in seconds."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="NOUS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    server: ServerConfig = ServerConfig()
    plugin_api_key: str = ""  # empty = no auth (dev mode)
    # Agent-browser settings
    agent_browser_path: str = ""  # Custom path to agent-browser binary (empty = auto-detect)

    # LLM provider API keys (shared across subsystems)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    # SearXNG search engine URL
    searxng_url: str = "http://localhost:8080"

    embedding: EmbeddingConfig = EmbeddingConfig()
    reranker: RerankerConfig = RerankerConfig()
    qdrant: QdrantConfig = QdrantConfig()
    forgetting: ForgettingConfig = ForgettingConfig()
    memorag: MemoRAGConfig = MemoRAGConfig()
    sandbox: SandboxConfig = SandboxConfig()
    memory_enrichment: MemoryEnrichmentConfig = MemoryEnrichmentConfig()
    auto_capture: AutoCaptureConfig = AutoCaptureConfig()
    portrait_gen: PortraitGenerationConfig = Field(default_factory=PortraitGenerationConfig)
    irodori: IrodoriConfig = Field(default_factory=IrodoriConfig)
    timezone: str = "Asia/Tokyo"
    data_root: str = "./data"
    log_level: str = "INFO"
    default_persona: str | None = None
    contradiction_threshold: float = 0.85
    duplicate_threshold: float = 0.90

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
        """Persona別DB格納ディレクトリ: {data_root}/memory"""
        return f"{self.data_root}/memory"

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
        """Skillsファイルディレクトリ: {data_root}/skills"""
        return f"{self.data_root}/skills"

    def ensure_directories(self) -> None:
        """起動時に必要なディレクトリを全て作成する。"""
        dirs = [
            self.data_dir,
            Path(self.data_root) / "logs",
            Path(self.data_root) / "backups",
            self.import_dir,
            Path(self.import_dir) / "done",
            self.cache_dir,
            Path(self.cache_dir) / "huggingface",
            Path(self.cache_dir) / "sentence_transformers",
            Path(self.cache_dir) / "torch",
            self.config_dir,
            self.skills_dir,
        ]
        # sandbox ディレクトリは sandbox 機能が有効な場合のみ作成
        if self.sandbox.enabled:
            dirs.append(Path(self.data_root) / "sandbox")

        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton (thread-safe via lru_cache)."""
    return Settings()
