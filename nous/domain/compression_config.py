"""コンテキスト圧縮設定 — CompressionConfig.

ChatConfig から分割された、コンテキスト圧縮に関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CompressionConfig(BaseModel):
    """コンテキスト圧縮設定。"""

    max_stored_messages: int = Field(default=200, description="保存する最大メッセージ数。")
    context_max_tokens: int | None = Field(default=None, description="コンテキストの最大トークン数。空欄でモデルから自動判定。")  # None = auto-detect from model
    context_compression_threshold: float = Field(default=0.8, description="コンテキスト圧縮を開始する使用率（0.5〜1.0）。")  # 0.5-1.0
    context_compression_mode: str = Field(default="auto", description="圧縮の強さ（auto / light / normal / aggressive）。")  # "light" | "normal" | "aggressive"
    context_keep_recent_turns: int = Field(default=2, description="要約せず完全に保持する最新ターン数。")
    context_compress_system_prompt: bool = Field(default=True, description="システムプロンプトも圧縮対象に含めます。")
    context_compress_history: bool = Field(default=True, description="会話履歴を圧縮対象に含めます。")
    memory_preload_count: int = Field(default=5, description="システムプロンプトに含める関連記憶の件数。0で全件検索。")  # 0=all, N=preload top N
    memory_digest_count: int = Field(default=5, description="毎ターン注入する最近の記憶の件数。0で無効。")  # 0=無効
    context_use_llm_summary: bool = Field(default=True, description="圧縮の要約にLLMを使います。")

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

    @field_validator("memory_digest_count")
    @classmethod
    def _clamp_digest_count(cls, v: int) -> int:
        return max(0, min(20, v))
