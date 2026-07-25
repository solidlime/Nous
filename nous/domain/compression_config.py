"""コンテキスト圧縮設定 — CompressionConfig.

ChatConfig から分割された、コンテキスト圧縮に関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class CompressionConfig(BaseModel):
    """コンテキスト圧縮設定。"""

    max_stored_messages: int = 200
    context_max_tokens: int | None = None  # None = auto-detect from model
    context_compression_threshold: float = 0.8  # 0.5-1.0
    context_compression_mode: str = "auto"  # "light" | "normal" | "aggressive"
    context_keep_recent_turns: int = 2
    context_compress_system_prompt: bool = True
    context_compress_history: bool = True
    memory_preload_count: int = 3  # 0=all, N=preload top N
    context_use_llm_summary: bool = True

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
        return max(0, v)  # 0 = truncation無効化

    @field_validator("memory_preload_count")
    @classmethod
    def _clamp_preload_count(cls, v: int) -> int:
        return max(0, min(20, v))
