from __future__ import annotations

import json
import logging
import os
import typing
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

# SQL type mapping for dynamic ALTER TABLE ADD COLUMN
_TYPE_SQL: dict[type, tuple[str, str]] = {
    bool: ("INTEGER", "0"),
    int: ("INTEGER", "0"),
    float: ("REAL", "0.0"),
    str: ("TEXT", "''"),
    list: ("TEXT", "''"),
    dict: ("TEXT", "''"),
    type(None): ("TEXT", "NULL"),
}


class ChatConfig(BaseModel):
    persona: str | None = None
    provider: str = "anthropic"
    model: str = ""
    api_key: str | None = None
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
    enabled_skills: list[str] = ["auto-memory", "auto-self-portrait", "goal-coach", "mood-sync", "recall-weaver"]
    # 画像生成
    image_gen_enabled: bool = False
    image_gen_provider: str = "comfyui"
    image_gen_comfyui_url: str = ""  # ComfyUI APIエンドポイント
    # ComfyUI 詳細設定
    image_gen_comfyui_checkpoint: str = ""
    image_gen_comfyui_loras: str = "[]"
    image_gen_comfyui_width: int = 1024
    image_gen_comfyui_height: int = 1024
    image_gen_comfyui_steps: int = 28
    image_gen_comfyui_cfg: float = 5.5
    image_gen_comfyui_sampler: str = "euler_ancestral"
    image_gen_comfyui_scheduler: str = "normal"
    image_gen_comfyui_seed: int = 0  # 0=ランダム
    image_gen_comfyui_denoise: float = 0.7
    image_gen_max_width: int = 1200
    image_gen_max_height: int = 1200
    # 自画像生成用プロンプト（キャラ外見のSDタグ・LoRAトリガーワード・トーンなどを含む固定プロンプト文字列）
    image_gen_self_portrait_prompt: str = ""
    image_gen_negative_prompt: str = ""  # negative prompt for image generation
    image_gen_full_body_prefix: str = "full body, standing, looking at viewer, "
    image_gen_portrait_prefix: str = "upper body, portrait, looking at viewer, "
    image_gen_selfie_prefix: str = "selfie, from below, mirror selfie, "
    image_gen_scene_prefix: str = "environment shot, full body, "
    # 高速化 LoRA
    image_gen_comfyui_speed_lora_path: str = "lcm_lora_sdxl.safetensors"
    image_gen_comfyui_speed_lora_weight: float = 1.0
    image_gen_comfyui_speed_lora_method: str = "lcm"  # lcm, lightning, hyper, tcd
    enable_memory_tools: bool = True
    disabled_tools: list[str] = []
    # 中央言語設定（ADR-001）
    language: str = "ja"  # "ja" | "en" | "zh" | "ko" | "auto"
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
    episode_search_enabled: bool = True
    # Voice / TTS settings (TE04)
    voice_enabled: bool = False
    voice_auto_play: bool = False
    voice_emotion_link: bool = True
    voice_model: str = ""
    voice_url: str = ""
    voice_volume: float = 1.0
    voice_speed: float = 1.0
    # Irodori advanced TTS parameters
    irodori_num_steps: int = 30
    irodori_cfg_scale_text: float = 3.2
    irodori_cfg_scale_speaker: float = 5.0
    irodori_cfg_scale_caption: float = 4.2
    irodori_chunk_min_chars: int = 85
    irodori_seed: int = 0
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
        return max(1, min(5000, v))

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


class ChatConfigRepository:
    """SQLite CRUD for ChatConfig, stored in the persona's memory.sqlite."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    # --- Schema introspection & auto-migration helpers ---

    def _get_db_columns(self) -> set[str]:
        """Return set of existing column names in chat_settings."""
        cursor = self._db.execute("PRAGMA table_info(chat_settings)")
        return {row[1] for row in cursor.fetchall()}

    def _ensure_columns(self, db_columns: set[str]) -> set[str]:
        """Add missing ChatConfig columns to chat_settings. Returns updated column set."""
        new_columns = set(db_columns)
        for field_name, field_info in ChatConfig.model_fields.items():
            if field_name in ("persona", "updated_at"):
                continue
            if field_name not in db_columns:
                col_type = self._infer_column_type(field_info)
                default = self._infer_default_value(field_info)
                sql = f"ALTER TABLE chat_settings ADD COLUMN {field_name} {col_type} DEFAULT {default}"
                self._db.execute(sql)
                logger.info("chat_config: added column %s (%s DEFAULT %s)", field_name, col_type, default)
                new_columns.add(field_name)
        return new_columns

    @staticmethod
    def _get_base_type(annotation: object) -> type:
        """Extract base Python type from a type annotation (handling Optional, Union, generics)."""
        if annotation is type(None):
            return type(None)
        origin = typing.get_origin(annotation)
        if origin is not None:
            if origin is typing.Union:
                non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
                if non_none:
                    return ChatConfigRepository._get_base_type(non_none[0])
                return type(None)
            if origin is list:
                return list
            if origin is dict:
                return dict
            return origin
        return annotation

    @staticmethod
    def _infer_column_type(field_info) -> str:
        """Infer SQL column type string from a Pydantic FieldInfo."""
        base = ChatConfigRepository._get_base_type(field_info.annotation)
        return _TYPE_SQL.get(base, ("TEXT", "''"))[0]

    @staticmethod
    def _infer_default_value(field_info) -> str:
        """Infer SQL DEFAULT expression from a Pydantic FieldInfo."""
        base = ChatConfigRepository._get_base_type(field_info.annotation)
        return _TYPE_SQL.get(base, ("TEXT", "''"))[1]

    @staticmethod
    def _to_bind_value(field_name: str, value: object) -> object:
        """Convert a ChatConfig field value to a bindable SQL value."""
        if value is None:
            return None
        field_info = ChatConfig.model_fields.get(field_name)
        if field_info is None:
            return value
        base = ChatConfigRepository._get_base_type(field_info.annotation)
        if base is bool:
            return int(value)
        if base in (list, dict):
            return json.dumps(value, ensure_ascii=False)
        return value

    def get(self, persona: str) -> ChatConfig:
        """Load config for persona, returning defaults if not found."""
        cursor = self._db.execute(
            "SELECT * FROM chat_settings WHERE persona = ?",
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
        """Insert or replace config for persona. Auto-creates missing columns."""
        now = format_iso(get_now())

        # 1. Introspect DB columns and auto-create missing ones
        db_columns = self._get_db_columns()
        db_columns = self._ensure_columns(db_columns)

        # 2. Build dynamic INSERT + UPSERT
        insert_fields: list[str] = []
        bind_values: list[object] = []
        update_set: list[str] = []

        for field_name in ChatConfig.model_fields:
            if field_name not in db_columns:
                continue
            insert_fields.append(field_name)
            if field_name == "persona":
                bind_values.append(config.persona)
            elif field_name == "updated_at":
                bind_values.append(now)
            else:
                value = getattr(config, field_name, None)
                bind_values.append(self._to_bind_value(field_name, value))
            if field_name != "persona":
                update_set.append(f"{field_name}=excluded.{field_name}")

        columns = ", ".join(insert_fields)
        placeholders = ", ".join("?" for _ in insert_fields)
        update_clause = ", ".join(update_set)

        sql = (
            f"INSERT INTO chat_settings ({columns})\n"
            f"VALUES ({placeholders})\n"
            f"ON CONFLICT(persona) DO UPDATE SET {update_clause}"
        )

        self._db.execute(sql, bind_values)
        self._db.commit()

    def delete(self, persona: str) -> None:
        self._db.execute("DELETE FROM chat_settings WHERE persona = ?", (persona,))
        self._db.commit()


# --- File-based repository (replaces SQLite chat_settings table) ---

class ChatConfigFileRepository:
    """JSON file-based CRUD for ChatConfig, stored per persona as config.json."""

    def __init__(self, data_root: str) -> None:
        self._data_root = data_root

    def _config_path(self, persona: str) -> str:
        return os.path.join(self._data_root, "persona", persona, "config.json")

    def _migrate_from_sqlite(self, persona: str) -> dict | None:
        """既存の memory.sqlite から chat_settings を読んで dict として返す。失敗時は None。"""
        import sqlite3 as _sqlite3
        db_path = os.path.join(self._data_root, "persona", persona, "memory.sqlite")
        if not os.path.exists(db_path):
            return None
        try:
            conn = _sqlite3.connect(db_path)
            conn.row_factory = _sqlite3.Row
            cursor = conn.execute("SELECT * FROM chat_settings WHERE persona = ?", (persona,))
            row = cursor.fetchone()
            conn.close()
            if row is None:
                return None
            columns = [d[0] for d in cursor.description]
            data = dict(zip(columns, row))
            # JSON フィールドのパース
            for jf in ("mcp_servers", "enabled_skills", "disabled_tools"):
                if data.get(jf) is not None and isinstance(data.get(jf), str):
                    try:
                        data[jf] = json.loads(data[jf])
                    except json.JSONDecodeError:
                        data[jf] = []
            # bool→int の逆変換 (SQLite は bool を INTEGER で保存している)
            bool_fields = {k for k, fi in ChatConfig.model_fields.items()
                           if ChatConfigRepository._get_base_type(fi.annotation) is bool}
            for bf in bool_fields:
                if bf in data and data[bf] is not None:
                    data[bf] = bool(data[bf])
            # 不要なキーを除去、None でないキーのみ
            nullable = {"updated_at", "context_max_tokens", "top_p"}
            result = {k: v for k, v in data.items()
                      if k in ChatConfig.model_fields and (v is not None or k in nullable)}
            return result
        except Exception:
            logger.warning("Migration from SQLite failed for persona '%s'", persona, exc_info=True)
            return None

    def get(self, persona: str) -> ChatConfig:
        """config.json を読む。不在ならSQLiteから移行、それもなければデフォルト値。"""
        path = self._config_path(persona)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                return ChatConfig(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning("Corrupted config.json for '%s': %s, falling back", persona, e)

        # マイグレーション試行
        migrated = self._migrate_from_sqlite(persona)
        if migrated:
            try:
                config = ChatConfig(**migrated)
                self.save(config)
                logger.info("Migrated chat_settings from SQLite to config.json for persona '%s'", persona)
                return config
            except ValidationError:
                logger.warning("Migrated data invalid for '%s', using defaults", persona)

        # デフォルト
        config = ChatConfig(persona=persona)
        self.save(config)
        return config

    def save(self, config: ChatConfig) -> None:
        """config.json にアトミック書き込み (write-temp → rename)。"""
        path = self._config_path(config.persona)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = config.model_dump(mode="json")
        data["updated_at"] = format_iso(get_now())
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)


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
