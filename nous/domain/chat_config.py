from __future__ import annotations

import json
import os
import warnings
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    import sqlite3

from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.shared.time_utils import format_iso, get_now
from nous.domain.value_objects import normalize_importance

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


class ChatConfig(BaseModel):
    persona: str | None = None
    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    max_tool_calls: int = 5
    auto_extract: bool = True
    extract_model: str = ""
    extract_max_tokens: int = 512
    tool_result_max_chars: int = 4000
    mcp_servers: list[dict] = []
    enabled_skills: list[str] = ["browser", "search", "memory"]
    # 画像生成
    image_gen_enabled: bool = False
    image_gen_provider: str = "openai"  # "openai" | "stability"
    image_gen_dalle_model: str = "dall-e-3"  # "dall-e-2" | "dall-e-3"
    image_gen_stability_url: str = ""  # SD WebUI APIエンドポイント
    enable_memory_tools: bool = True
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
    # Chat history display (separate from context window)
    display_history_turns: int = 20
    # Housekeeping auto-trigger threshold (total active goals+promises)
    housekeeping_threshold: int = 10
    sandbox_enabled: bool = True
    debug_mode: bool = False
    # === Context compression (v2.1) ===
    max_window_turns: int = 100  # backward-compat; prefer max_stored_messages
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
    # HiMem 2-tier: Episode Memory consolidation
    episode_consolidation_enabled: bool = True
    episode_search_enabled: bool = True
    updated_at: str | None = None

    def model_post_init(self, __context) -> None:
        """Post-init hook: emit deprecation warnings for legacy fields."""
        if self.max_window_turns is not None:
            warnings.warn(
                "max_window_turns is deprecated, use max_stored_messages instead",
                DeprecationWarning,
                stacklevel=2,
            )

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

    @field_validator("display_history_turns")
    @classmethod
    def _clamp_display_history_turns(cls, v: int) -> int:
        return max(1, min(200, v))

    @field_validator("housekeeping_threshold")
    @classmethod
    def _clamp_housekeeping_threshold(cls, v: int) -> int:
        return max(1, min(100, v))

    @field_validator("max_window_turns")
    @classmethod
    def _clamp_window_turns(cls, v: int) -> int:
        return max(1, min(500, v))

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
        row = self._db.execute(
            "SELECT persona, provider, model, api_key, base_url, system_prompt, "
            "temperature, max_tokens, max_window_turns, max_tool_calls, updated_at, "
            "auto_extract, extract_model, extract_max_tokens, "
            "tool_result_max_chars, mcp_servers, enabled_skills, "
            "reflection_enabled, reflection_threshold, reflection_min_interval_hours, "
            "session_summarize, "
            "retrieval_recency_weight, retrieval_importance_weight, retrieval_relevance_weight, "
            "display_history_turns, housekeeping_threshold, sandbox_enabled, "
            "mental_model_enabled, mental_model_min_samples, "
            "max_stored_messages, context_max_tokens, context_compression_threshold, "
            "context_compression_mode, context_keep_recent_turns, "
            "context_compress_system_prompt, context_compress_history, "
            "memory_preload_count, enable_parallel_tools, "
            "image_gen_enabled, image_gen_provider, image_gen_dalle_model, image_gen_stability_url, "
            "enable_memory_tools, debug_mode, "
            "dynamic_temperature, emotion_temperature_scale, top_p, "
            "context_use_llm_summary, episode_consolidation_enabled, episode_search_enabled "
            "FROM chat_settings WHERE persona = ?",
            (persona,),
        ).fetchone()
        if row is None:
            return ChatConfig(persona=persona)
        return ChatConfig(
            persona=row[0],
            provider=row[1] or "anthropic",
            model=row[2] or "",
            api_key=row[3] or "",
            base_url=row[4] or "",
            system_prompt=row[5] or "",
            temperature=float(row[6]) if row[6] is not None else 0.7,
            max_tokens=int(row[7]) if row[7] is not None else 2048,
            max_window_turns=int(row[8]) if row[8] is not None else 100,
            max_tool_calls=int(row[9]) if row[9] is not None else 5,
            updated_at=row[10],
            auto_extract=bool(row[11]) if row[11] is not None else True,
            extract_model=row[12] or "",
            extract_max_tokens=int(row[13]) if row[13] is not None else 512,
            tool_result_max_chars=int(row[14]) if row[14] is not None else 4000,
            mcp_servers=json.loads(row[15] or "[]"),
            enabled_skills=json.loads(row[16] or "[]"),
            reflection_enabled=bool(row[17]) if row[17] is not None else True,
            reflection_threshold=float(row[18]) if row[18] is not None else 1.0,
            reflection_min_interval_hours=float(row[19]) if row[19] is not None else 1.0,
            session_summarize=bool(row[20]) if row[20] is not None else True,
            retrieval_recency_weight=float(row[21]) if row[21] is not None else 0.3,
            retrieval_importance_weight=float(row[22]) if row[22] is not None else 0.3,
            retrieval_relevance_weight=float(row[23]) if row[23] is not None else 0.4,
            display_history_turns=int(row[24]) if row[24] is not None else 20,
            housekeeping_threshold=int(row[25]) if row[25] is not None else 10,
            sandbox_enabled=bool(row[26]) if row[26] is not None else False,
            mental_model_enabled=bool(row[27]) if len(row) > 27 and row[27] is not None else True,
            mental_model_min_samples=int(row[28]) if len(row) > 28 and row[28] is not None else 3,
            max_stored_messages=int(row[29])
            if len(row) > 29 and row[29] is not None
            else (max(2, int(row[8]) * 2) if row[8] is not None else 200),
            context_max_tokens=int(row[30]) if len(row) > 30 and row[30] is not None else None,
            context_compression_threshold=float(row[31]) if len(row) > 31 and row[31] is not None else 0.8,
            context_compression_mode=row[32] if len(row) > 32 and row[32] else "auto",
            context_keep_recent_turns=int(row[33]) if len(row) > 33 and row[33] is not None else 2,
            context_compress_system_prompt=bool(row[34]) if len(row) > 34 and row[34] is not None else True,
            context_compress_history=bool(row[35]) if len(row) > 35 and row[35] is not None else True,
            memory_preload_count=int(row[36]) if len(row) > 36 and row[36] is not None else 3,
            enable_parallel_tools=bool(row[37]) if len(row) > 37 and row[37] is not None else True,
            image_gen_enabled=bool(row[38]) if len(row) > 38 and row[38] is not None else False,
            image_gen_provider=row[39] if len(row) > 39 and row[39] else "openai",
            image_gen_dalle_model=row[40] if len(row) > 40 and row[40] else "dall-e-3",
            image_gen_stability_url=row[41] if len(row) > 41 and row[41] else "",
            enable_memory_tools=bool(row[42]) if len(row) > 42 and row[42] is not None else True,
            debug_mode=bool(row[43]) if len(row) > 43 and row[43] is not None else False,
            dynamic_temperature=bool(row[44]) if len(row) > 44 and row[44] is not None else True,
            emotion_temperature_scale=float(row[45]) if len(row) > 45 and row[45] is not None else 0.2,
            top_p=float(row[46]) if len(row) > 46 and row[46] is not None else None,
            context_use_llm_summary=bool(row[47]) if len(row) > 47 and row[47] is not None else True,
            episode_consolidation_enabled=bool(row[48]) if len(row) > 48 and row[48] is not None else True,
            episode_search_enabled=bool(row[49]) if len(row) > 49 and row[49] is not None else True,
        )

    def save(self, config: ChatConfig) -> None:
        """Insert or replace config for persona."""
        now = format_iso(get_now())
        self._db.execute(
            """
            INSERT INTO chat_settings
                (persona, provider, model, api_key, base_url, system_prompt,
                 temperature, max_tokens, max_window_turns, max_tool_calls,
                 auto_extract, extract_model, extract_max_tokens,
                 tool_result_max_chars, mcp_servers, enabled_skills,
                 reflection_enabled, reflection_threshold, reflection_min_interval_hours,
                 session_summarize,
                 retrieval_recency_weight, retrieval_importance_weight, retrieval_relevance_weight,
                 display_history_turns, housekeeping_threshold, sandbox_enabled,
                 mental_model_enabled, mental_model_min_samples,
                 max_stored_messages, context_max_tokens, context_compression_threshold,
                 context_compression_mode, context_keep_recent_turns,
                  context_compress_system_prompt, context_compress_history,
                  memory_preload_count, enable_parallel_tools,
                   image_gen_enabled, image_gen_provider, image_gen_dalle_model, image_gen_stability_url,
                   enable_memory_tools, debug_mode,
                   dynamic_temperature, emotion_temperature_scale, top_p,
                   context_use_llm_summary, episode_consolidation_enabled, episode_search_enabled,
                   updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(persona) DO UPDATE SET
                provider=excluded.provider,
                model=excluded.model,
                api_key=excluded.api_key,
                base_url=excluded.base_url,
                system_prompt=excluded.system_prompt,
                temperature=excluded.temperature,
                max_tokens=excluded.max_tokens,
                max_window_turns=excluded.max_window_turns,
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
                housekeeping_threshold=excluded.housekeeping_threshold,
                sandbox_enabled=excluded.sandbox_enabled,
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
                 enable_memory_tools=excluded.enable_memory_tools,
                 debug_mode=excluded.debug_mode,
                 dynamic_temperature=excluded.dynamic_temperature,
                 emotion_temperature_scale=excluded.emotion_temperature_scale,
                 top_p=excluded.top_p,
                 context_use_llm_summary=excluded.context_use_llm_summary,
                 episode_consolidation_enabled=excluded.episode_consolidation_enabled,
                 episode_search_enabled=excluded.episode_search_enabled,
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
                config.max_window_turns,
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
                config.housekeeping_threshold,
                int(config.sandbox_enabled),
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
                int(config.enable_memory_tools),
                int(config.debug_mode),
                int(config.dynamic_temperature),
                config.emotion_temperature_scale,
                config.top_p,
                int(config.context_use_llm_summary),
                int(config.episode_consolidation_enabled),
                int(config.episode_search_enabled),
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
