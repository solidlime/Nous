from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError, field_validator

from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.shared.time_utils import format_iso, get_now
from nous.domain.value_objects import normalize_importance

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import sqlite3

# Backward-compat env var names for API keys per provider (legacy, without NOUS_ prefix)
_ENV_API_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Default model names per provider
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-5",
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o",
}

# Default base URLs per provider (empty means use SDK default)
_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "",
    "openai": "",
    "openrouter": "https://openrouter.ai/api/v1",
}


# 後方互換のため定数は残すが内容は空（各 persona 個別生成）
DEFAULT_MCP_SERVERS: list[dict] = []


class ChatConfig(BaseModel):
    persona: str | None = None
    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 8192
    max_tool_calls: int = 5
    auto_extract: bool = True
    extract_model: str = ""
    extract_max_tokens: int = 512
    tool_result_max_chars: int = 4000
    mcp_servers: list[dict] = []
    enabled_skills: list[str] = ["search", "memory"]
    # 画像生成
    image_gen_enabled: bool = False
    image_gen_provider: str = "openai"  # "openai" | "stability"
    image_gen_dalle_model: str = "dall-e-3"  # "dall-e-2" | "dall-e-3"
    image_gen_stability_url: str = ""  # SD WebUI APIエンドポイント
    image_gen_comfyui_url: str = ""  # ComfyUI APIエンドポイント
    image_gen_gemini_model: str = "google/gemini-2.5-flash-image"
    image_gen_replicate_model: str = "black-forest-labs/flux-schnell"
    image_gen_replicate_api_key: str = ""
    enable_memory_tools: bool = True
    disabled_tools: list[str] = []
    # Generative Agents-style reflection
    reflection_enabled: bool = True
    reflection_threshold: float = 1.0  # sum of importance scores to trigger reflection
    reflection_min_interval_hours: float = 1.0
    # Mental Model abstraction
    mental_model_enabled: bool = True
    mental_model_min_samples: int = 3
    # Session summarization
    session_summarize: bool = True
    # Retrieval composite scoring weights
    retrieval_recency_weight: float = 0.3
    retrieval_importance_weight: float = 0.3
    retrieval_relevance_weight: float = 0.4
    retrieval_rrf_k: float = 5.0  # RRF k parameter for memory search relevance scoring
    # Chat history display (separate from context window)
    display_history_turns: int = 10
    debug_mode: bool = False
    # === Context compression (v2.1) ===
    # (max_window_turns removed — use max_stored_messages)
    max_stored_messages: int = 200
    context_max_tokens: int | None = None  # None = auto-detect from model
    context_compression_threshold: float = 0.8  # 0.5-1.0
    context_compression_mode: str = "auto"  # "light" | "normal" | "aggressive"
    context_keep_recent_turns: int = 2
    context_compress_system_prompt: bool = True
    context_compress_history: bool = True
    memory_preload_count: int = 3  # 0=all, N=preload top N
    enable_parallel_tools: bool = True
    # LLM context summarization (CompressStep Stage 4)
    context_use_llm_summary: bool = True
    # Dynamic temperature + top_p (TA02)
    dynamic_temperature: bool = True
    emotion_temperature_scale: float = 0.2
    top_p: float | None = None
    # Dynamic tool selection (P22): True の時のみ条件付きツールを制限可
    dynamic_tool_selection: bool = True
    # HiMem 2-tier: Episode Memory consolidation
    episode_consolidation_enabled: bool = True
    episode_search_enabled: bool = True
    # Phase 1: per-persona toggles with global fallback
    irodori_enabled: bool = False
    # Voice / TTS settings (TE04)
    voice_auto_play: bool = False
    voice_emotion_link: bool = True
    voice_model: str = ""
    updated_at: str | None = None

    @field_validator("temperature")
    @classmethod
    def _clamp_temperature(cls, v: float) -> float:
        return max(0.0, min(2.0, v))

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

    @field_validator("reflection_threshold")
    @classmethod
    def _clamp_reflection_threshold(cls, v: float) -> float:
        return max(0.1, min(100.0, v))

    @field_validator("reflection_min_interval_hours")
    @classmethod
    def _clamp_reflection_interval(cls, v: float) -> float:
        return max(0.0, min(168.0, v))

    @field_validator("retrieval_recency_weight", "retrieval_importance_weight", "retrieval_relevance_weight")
    @classmethod
    def _clamp_retrieval_weights(cls, v: float) -> float:
        return normalize_importance(v)

    @field_validator("retrieval_rrf_k")
    @classmethod
    def _clamp_retrieval_rrf_k(cls, v: float) -> float:
        return max(0.1, min(100.0, v))

    @field_validator("display_history_turns")
    @classmethod
    def _clamp_display_history_turns(cls, v: int) -> int:
        return max(1, min(200, v))

    @field_validator("context_compression_threshold")
    @classmethod
    def _clamp_compression_threshold(cls, v: float) -> float:
        return max(0.5, min(1.0, v))

    @field_validator("context_compression_mode")
    @classmethod
    def _validate_compression_mode(cls, v: str) -> str:
        if v not in ("auto", "light", "normal", "aggressive"):
            return "auto"
        return v

    @field_validator("context_keep_recent_turns")
    @classmethod
    def _clamp_keep_recent(cls, v: int) -> int:
        return max(1, min(20, v))

    @field_validator("memory_preload_count")
    @classmethod
    def _clamp_preload_count(cls, v: int) -> int:
        return max(0, min(20, v))

    @field_validator("emotion_temperature_scale")
    @classmethod
    def _clamp_emotion_temperature_scale(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("top_p")
    @classmethod
    def _clamp_top_p(cls, v: float | None) -> float | None:
        if v is None:
            return None
        return max(0.0, min(1.0, v))

    def get_effective_api_key(self) -> str:
        """Return stored API key or fall back via RuntimeConfigManager."""
        if self.api_key:
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


class ChatConfigRepository:
    """SQLite CRUD for ChatConfig, stored in the persona's memory.sqlite."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def get(self, persona: str) -> ChatConfig:
        """Load config for persona, returning defaults if not found."""
        cursor = self._db.execute(
            "SELECT persona, provider, model, api_key, base_url, system_prompt, "
            "temperature, max_tokens, "
            "max_tool_calls, updated_at, "
            "auto_extract, extract_model, extract_max_tokens, "
            "tool_result_max_chars, mcp_servers, enabled_skills, "
            "reflection_enabled, reflection_threshold, reflection_min_interval_hours, "
            "session_summarize, "
            "retrieval_recency_weight, retrieval_importance_weight, retrieval_relevance_weight, "
            "display_history_turns, "
            "mental_model_enabled, mental_model_min_samples, "
            "max_stored_messages, context_max_tokens, context_compression_threshold, "
            "context_compression_mode, context_keep_recent_turns, "
            "context_compress_system_prompt, context_compress_history, "
            "memory_preload_count, enable_parallel_tools, "
            "image_gen_enabled, image_gen_provider, image_gen_dalle_model, image_gen_stability_url, image_gen_comfyui_url, "
            "image_gen_gemini_model, image_gen_replicate_model, image_gen_replicate_api_key, "
            "enable_memory_tools, debug_mode, "
            "dynamic_temperature, emotion_temperature_scale, top_p, "
            "context_use_llm_summary, episode_consolidation_enabled, episode_search_enabled, "
            "retrieval_rrf_k, "
            "dynamic_tool_selection, "
            "irodori_enabled, "
            "voice_auto_play, voice_emotion_link, voice_model, "
            "disabled_tools "
            "FROM chat_settings WHERE persona = ?",
            (persona,),
        )
        row = cursor.fetchone()
        if row is None:
            return ChatConfig(persona=persona)

        # Dynamic column-name → value mapping (not hardcoded indices)
        columns = [d[0] for d in cursor.description]
        data = dict(zip(columns, row, strict=False))

        # Parse stored JSON fields with resilience
        for jf in ("mcp_servers", "enabled_skills", "disabled_tools"):
            if data.get(jf) is not None:
                try:
                    data[jf] = json.loads(data[jf])
                except json.JSONDecodeError:
                    logger.warning("chat_config.get: corrupted JSON in '%s', falling back to []", jf)
                    data[jf] = []

        # Build kwargs: only pass known ChatConfig fields, skip None unless nullable
        nullable = {"updated_at", "context_max_tokens", "top_p"}
        kwargs = {k: v for k, v in data.items() if k in ChatConfig.model_fields and (v is not None or k in nullable)}

        # Construct with resilience — strip invalid fields on ValidationError
        try:
            return ChatConfig(**kwargs)
        except ValidationError as e:
            for err in e.errors():
                field = err["loc"][0] if err.get("loc") else None
                if field and field in kwargs:
                    logger.warning("chat_config.get: stripping invalid field '%s': %s", field, err["msg"])
                    kwargs.pop(field)
            try:
                return ChatConfig(**kwargs)
            except ValidationError:
                logger.warning("chat_config.get: still invalid after stripping fields, returning defaults")
                return ChatConfig(persona=persona)

    def get_or_create(self, persona: str) -> ChatConfig:
        """Get existing config or create new with defaults for fresh personas."""
        config = self.get(persona)
        # Only fill defaults for truly new personas (no mcp_servers configured)
        if not config.mcp_servers:
            config.mcp_servers = []
            self.save(config)
        return config

    def save(self, config: ChatConfig) -> None:
        """Insert or replace config for persona."""
        now = format_iso(get_now())
        self._db.execute(
            """
            INSERT INTO chat_settings
                (persona, provider, model, api_key, base_url, system_prompt,
                 temperature, max_tokens, max_tool_calls,
                 auto_extract, extract_model, extract_max_tokens,
                 tool_result_max_chars, mcp_servers, enabled_skills,
                 reflection_enabled, reflection_threshold, reflection_min_interval_hours,
                 session_summarize,
                 retrieval_recency_weight, retrieval_importance_weight, retrieval_relevance_weight,
                 display_history_turns,
                 mental_model_enabled, mental_model_min_samples,
                 max_stored_messages, context_max_tokens, context_compression_threshold,
                 context_compression_mode, context_keep_recent_turns,
                  context_compress_system_prompt, context_compress_history,
                  memory_preload_count, enable_parallel_tools,
                    image_gen_enabled, image_gen_provider, image_gen_dalle_model, image_gen_stability_url, image_gen_comfyui_url,
                    image_gen_gemini_model, image_gen_replicate_model, image_gen_replicate_api_key,
                    enable_memory_tools, debug_mode,
                    dynamic_temperature, emotion_temperature_scale, top_p,
                     context_use_llm_summary, episode_consolidation_enabled, episode_search_enabled,
                     retrieval_rrf_k,
                       dynamic_tool_selection,
                       irodori_enabled,
                       voice_auto_play, voice_emotion_link, voice_model,
                        disabled_tools,
                        updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(persona) DO UPDATE SET
                provider=excluded.provider,
                model=excluded.model,
                api_key=excluded.api_key,
                base_url=excluded.base_url,
                system_prompt=excluded.system_prompt,
                temperature=excluded.temperature,
                max_tokens=excluded.max_tokens,
                 max_tool_calls=excluded.max_tool_calls,
                auto_extract=excluded.auto_extract,
                extract_model=excluded.extract_model,
                extract_max_tokens=excluded.extract_max_tokens,
                tool_result_max_chars=excluded.tool_result_max_chars,
                mcp_servers=excluded.mcp_servers,
                enabled_skills=excluded.enabled_skills,
                reflection_enabled=excluded.reflection_enabled,
                reflection_threshold=excluded.reflection_threshold,
                reflection_min_interval_hours=excluded.reflection_min_interval_hours,
                session_summarize=excluded.session_summarize,
                retrieval_recency_weight=excluded.retrieval_recency_weight,
                retrieval_importance_weight=excluded.retrieval_importance_weight,
                retrieval_relevance_weight=excluded.retrieval_relevance_weight,
                display_history_turns=excluded.display_history_turns,
                mental_model_enabled=excluded.mental_model_enabled,
                mental_model_min_samples=excluded.mental_model_min_samples,
                max_stored_messages=excluded.max_stored_messages,
                context_max_tokens=excluded.context_max_tokens,
                context_compression_threshold=excluded.context_compression_threshold,
                context_compression_mode=excluded.context_compression_mode,
                context_keep_recent_turns=excluded.context_keep_recent_turns,
                context_compress_system_prompt=excluded.context_compress_system_prompt,
                context_compress_history=excluded.context_compress_history,
                 memory_preload_count=excluded.memory_preload_count,
                 enable_parallel_tools=excluded.enable_parallel_tools,
                 image_gen_enabled=excluded.image_gen_enabled,
                 image_gen_provider=excluded.image_gen_provider,
                 image_gen_dalle_model=excluded.image_gen_dalle_model,
                 image_gen_stability_url=excluded.image_gen_stability_url,
                 image_gen_comfyui_url=excluded.image_gen_comfyui_url,
                 image_gen_gemini_model=excluded.image_gen_gemini_model,
                 image_gen_replicate_model=excluded.image_gen_replicate_model,
                 image_gen_replicate_api_key=excluded.image_gen_replicate_api_key,
                 enable_memory_tools=excluded.enable_memory_tools,
                 debug_mode=excluded.debug_mode,
                 dynamic_temperature=excluded.dynamic_temperature,
                 emotion_temperature_scale=excluded.emotion_temperature_scale,
                 top_p=excluded.top_p,
                 context_use_llm_summary=excluded.context_use_llm_summary,
                 episode_consolidation_enabled=excluded.episode_consolidation_enabled,
                 episode_search_enabled=excluded.episode_search_enabled,
                 retrieval_rrf_k=excluded.retrieval_rrf_k,
                 dynamic_tool_selection=excluded.dynamic_tool_selection,
                 irodori_enabled=excluded.irodori_enabled,
                 voice_auto_play=excluded.voice_auto_play,
                  voice_emotion_link=excluded.voice_emotion_link,
                  voice_model=excluded.voice_model,
                  disabled_tools=excluded.disabled_tools,
                 updated_at=excluded.updated_at
            """,
            (
                config.persona,
                config.provider,
                config.model,
                config.api_key,
                config.base_url,
                config.system_prompt,
                config.temperature,
                config.max_tokens,
                config.max_tool_calls,
                int(config.auto_extract),
                config.extract_model,
                config.extract_max_tokens,
                config.tool_result_max_chars,
                json.dumps(config.mcp_servers, ensure_ascii=False),
                json.dumps(config.enabled_skills, ensure_ascii=False),
                int(config.reflection_enabled),
                config.reflection_threshold,
                config.reflection_min_interval_hours,
                int(config.session_summarize),
                config.retrieval_recency_weight,
                config.retrieval_importance_weight,
                config.retrieval_relevance_weight,
                config.display_history_turns,
                int(config.mental_model_enabled),
                config.mental_model_min_samples,
                config.max_stored_messages,
                config.context_max_tokens,
                config.context_compression_threshold,
                config.context_compression_mode,
                config.context_keep_recent_turns,
                int(config.context_compress_system_prompt),
                int(config.context_compress_history),
                config.memory_preload_count,
                int(config.enable_parallel_tools),
                int(config.image_gen_enabled),
                config.image_gen_provider,
                config.image_gen_dalle_model,
                config.image_gen_stability_url,
                config.image_gen_comfyui_url,
                config.image_gen_gemini_model,
                config.image_gen_replicate_model,
                config.image_gen_replicate_api_key,
                int(config.enable_memory_tools),
                int(config.debug_mode),
                int(config.dynamic_temperature),
                config.emotion_temperature_scale,
                config.top_p,
                int(config.context_use_llm_summary),
                int(config.episode_consolidation_enabled),
                int(config.episode_search_enabled),
                config.retrieval_rrf_k,
                int(config.dynamic_tool_selection),
                int(config.irodori_enabled),
                int(config.voice_auto_play),
                int(config.voice_emotion_link),
                config.voice_model,
                json.dumps(config.disabled_tools, ensure_ascii=False),
                now,
            ),
        )
        self._db.commit()

    def delete(self, persona: str) -> None:
        self._db.execute("DELETE FROM chat_settings WHERE persona = ?", (persona,))
        self._db.commit()


class ImageAttachment(BaseModel):
    """チャットに添付された画像。base64_data は data: URL プレフィックスなしの生Base64。"""

    filename: str
    mime_type: str  # e.g. "image/png", "image/jpeg"
    base64_data: str  # raw base64 (without data: URL prefix)

    @field_validator("base64_data")
    @classmethod
    def _validate_size(cls, v: str) -> str:
        """10MB上限チェック。Base64長さ×3/4 ≒ デコード後サイズ。"""
        max_bytes = 10 * 1024 * 1024  # 10MB
        # 余裕をもって判定: パディング除去後の有効長
        decoded_estimate = len(v) * 3 // 4
        if decoded_estimate > max_bytes:
            raise ValueError(f"Image data exceeds 10MB limit (estimated {decoded_estimate} bytes > {max_bytes} bytes)")
        return v
