"""ChatConfig — 全設定を集約するFacade Pydanticモデル。

ProviderConfig / SessionConfig / CompressionConfig / ToolConfig の4つの
サブ設定を内包し、後方互換のため全フィールドに直接アクセスできる。
"""

from __future__ import annotations

import json
import logging
import os
import typing
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticUndefined

from nous.domain.compression_config import CompressionConfig

# Sub-config imports
from nous.domain.provider_config import ProviderConfig
from nous.domain.session_config import SessionConfig
from nous.domain.shared.time_utils import format_iso, get_now
from nous.domain.tool_config import ToolConfig

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import sqlite3

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

# Sub-config field name → class mapping
_SUB_CONFIG_MAP: dict[str, type[BaseModel]] = {
    "provider_config": ProviderConfig,
    "session_config": SessionConfig,
    "compression_config": CompressionConfig,
    "tool_config": ToolConfig,
}


# ──────────────────────────────────────────────
# Facade
# ──────────────────────────────────────────────


class ChatConfig(BaseModel):
    """全設定を集約するFacade。

    内部で ProviderConfig / SessionConfig / CompressionConfig / ToolConfig の
    4つのサブ設定を保持。後方互換のため、サブ設定の全フィールドに
    直接アクセスできる (``ChatConfig().api_key`` / ``ChatConfig().model`` 等)。
    シリアライズ時は自動的にフラット化される。
    """

    persona: str | None = None
    updated_at: str | None = None
    character_judge_enabled: bool = True  # キャラ一貫性判定器（Task 8・非破壊フラグ）
    provider_config: ProviderConfig = Field(default_factory=ProviderConfig)
    session_config: SessionConfig = Field(default_factory=SessionConfig)
    compression_config: CompressionConfig = Field(default_factory=CompressionConfig)
    tool_config: ToolConfig = Field(default_factory=ToolConfig)

    # ── コンストラクタ ──────────────────────────

    def __init__(self, /, **data: Any) -> None:
        # Pydantic v2 は __init__ で model_validator(mode="before") を呼ぶので、
        # フラットキーワードは validator で自動分配される。
        super().__init__(**data)

    # ── model_validator: フラットキーワードをサブ設定に分配 ──

    @model_validator(mode="before")
    @classmethod
    def _distribute_flat_fields(cls, data: Any) -> Any:
        """Accept flat field names (api_key, model, ...) AND nested configs."""
        if not isinstance(data, dict):
            return data

        # サブ設定の全フィールド名セット
        all_sub_keys: set[str] = set()
        for sub_cls in _SUB_CONFIG_MAP.values():
            all_sub_keys.update(sub_cls.model_fields)

        # フラットキーが1つでもあるか？
        if not any(k in all_sub_keys for k in data):
            return data  # そのまま通過（既にネスト形式）

        # フラットキーを対応するサブ設定 dict に振り分け
        result: dict[str, Any] = {}
        for k, v in data.items():
            placed = False
            for cfg_name, sub_cls in _SUB_CONFIG_MAP.items():
                if k in sub_cls.model_fields:
                    existing = result.get(cfg_name)
                    if existing is None:
                        result[cfg_name] = {k: v}
                    elif isinstance(existing, dict):
                        existing[k] = v
                    elif isinstance(existing, BaseModel):
                        # model instance → dict 変換してマージ
                        merged = existing.model_dump()
                        merged[k] = v
                        result[cfg_name] = merged
                    placed = True
                    break
            if not placed:
                result[k] = v
        return result

    # ── __getattr__: 後方互換のためのフィールド委譲 ──

    def __getattr__(self, name: str) -> Any:
        for sub in (
            self.provider_config,
            self.session_config,
            self.compression_config,
            self.tool_config,
        ):
            if hasattr(sub, name):
                return getattr(sub, name)
        msg = f"'{type(self).__name__}' has no attribute '{name}'"
        raise AttributeError(msg)

    def __setattr__(self, name: str, value: Any) -> None:
        for sub in (
            self.provider_config,
            self.session_config,
            self.compression_config,
            self.tool_config,
        ):
            if name in type(sub).model_fields:
                setattr(sub, name, value)
                return
        super().__setattr__(name, value)

    # ── シリアライズ: フラット化 ──

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        d = super().model_dump(**kwargs)
        # サブ設定をフラットに展開
        for cfg_field in (
            "provider_config",
            "session_config",
            "compression_config",
            "tool_config",
        ):
            sub = d.pop(cfg_field, None)
            if isinstance(sub, dict):
                d.update(sub)
        return d

    # ── 全フラットフィールド一覧（Repository で使用） ──

    @classmethod
    def _all_flat_fields(cls) -> dict[str, FieldInfo]:
        """Return all fields including sub-config fields flattened."""
        fields: dict[str, FieldInfo] = {}
        for name, info in cls.model_fields.items():
            sub_cls = _SUB_CONFIG_MAP.get(name)
            if sub_cls is not None:
                for sub_name, sub_info in sub_cls.model_fields.items():
                    fields[sub_name] = sub_info
            else:
                fields[name] = info
        return fields

    # ── 後方互換ヘルパーメソッド（ProviderConfig に委譲） ──

    def get_effective_api_key(self) -> str:
        return self.provider_config.get_effective_api_key()

    def get_effective_model(self) -> str:
        return self.provider_config.get_effective_model()

    def get_effective_base_url(self) -> str:
        return self.provider_config.get_effective_base_url()

    def is_configured(self) -> bool:
        return self.provider_config.is_configured()

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


# ──────────────────────────────────────────────
# Repository: SQLite CRUD (自動マイグレーション付き)
# ──────────────────────────────────────────────


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
        for field_name, field_info in ChatConfig._all_flat_fields().items():
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
        """Infer SQL DEFAULT expression from a Pydantic FieldInfo (pydantic default 優先)."""
        base = ChatConfigRepository._get_base_type(field_info.annotation)
        _, type_default = _TYPE_SQL.get(base, ("TEXT", "''"))
        default = getattr(field_info, "default", None)
        if default is PydanticUndefined:
            factory = getattr(field_info, "default_factory", None)
            try:
                default = factory() if factory else None
            except Exception:
                default = None
        if default is None:
            return type_default
        if base is bool:
            return str(int(bool(default)))
        if base is int:
            return str(int(typing.cast("int", default)))
        if base is float:
            return str(float(typing.cast("float", default)))
        return "'" + str(default).replace("'", "''") + "'"

    @staticmethod
    def _to_bind_value(field_name: str, value: object) -> object:
        """Convert a ChatConfig field value to a bindable SQL value."""
        if value is None:
            return None
        all_fields = ChatConfig._all_flat_fields()
        field_info = all_fields.get(field_name)
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
        for jf in ("mcp_servers", "enabled_skills", "disabled_tools", "image_gen_presets"):
            if data.get(jf) is not None:
                try:
                    data[jf] = json.loads(data[jf])
                except json.JSONDecodeError:
                    logger.warning("chat_config.get: corrupted JSON in '%s', falling back to []", jf)
                    data[jf] = []

        # Build kwargs: only pass known ChatConfig fields, skip None unless nullable
        nullable = {"updated_at", "context_max_tokens", "top_p"}
        all_fields = ChatConfig._all_flat_fields()
        kwargs = {k: v for k, v in data.items() if k in all_fields and (v is not None or k in nullable)}

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

        for field_name in ChatConfig._all_flat_fields():
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
            f"INSERT INTO chat_settings ({columns})\n"  # column names from dataclass fields x DB introspection; values bound via params  # nosec B608
            f"VALUES ({placeholders})\n"
            f"ON CONFLICT(persona) DO UPDATE SET {update_clause}"
        )

        self._db.execute(sql, bind_values)
        self._db.commit()

    def delete(self, persona: str) -> None:
        self._db.execute("DELETE FROM chat_settings WHERE persona = ?", (persona,))
        self._db.commit()


# ──────────────────────────────────────────────
# File-based repository (replaces SQLite chat_settings table)
# ──────────────────────────────────────────────


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
            data = dict(zip(columns, row, strict=False))
            # JSON フィールドのパース
            for jf in ("mcp_servers", "enabled_skills", "disabled_tools", "image_gen_presets"):
                if data.get(jf) is not None and isinstance(data.get(jf), str):
                    try:
                        data[jf] = json.loads(data[jf])
                    except json.JSONDecodeError:
                        data[jf] = []
            # bool→int の逆変換 (SQLite は bool を INTEGER で保存している)
            all_fields = ChatConfig._all_flat_fields()
            bool_fields = {
                k for k, fi in all_fields.items() if ChatConfigRepository._get_base_type(fi.annotation) is bool
            }
            for bf in bool_fields:
                if bf in data and data[bf] is not None:
                    data[bf] = bool(data[bf])
            # 不要なキーを除去、None でないキーのみ
            nullable = {"updated_at", "context_max_tokens", "top_p"}
            result = {k: v for k, v in data.items() if k in all_fields and (v is not None or k in nullable)}
            return result
        except Exception:
            logger.warning("Migration from SQLite failed for persona '%s'", persona, exc_info=True)
            return None

    def get(self, persona: str) -> ChatConfig:
        """config.json を読む。不在ならSQLiteから移行、それもなければデフォルト値。"""
        path = self._config_path(persona)
        if os.path.exists(path):
            try:
                with open(path) as f:
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


# ──────────────────────────────────────────────
# ImageAttachment (チャットに添付された画像)
# ──────────────────────────────────────────────


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
