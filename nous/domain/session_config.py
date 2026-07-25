"""セッション管理設定 — SessionConfig.

ChatConfig から分割された、セッション管理・リフレクション・メモリ拡張・
音声・忘却・MemoRAGに関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from nous.domain.value_objects import normalize_importance


class SessionConfig(BaseModel):
    """セッション管理・メモリ設定。"""

    # 基本設定
    system_prompt: str = ""
    language: str = "ja"  # "ja" | "en" | "zh" | "ko" | "auto"
    debug_mode: bool = False
    display_history_turns: int = 10
    show_message_timestamps: bool = False  # チャットメッセージにタイムスタンプを表示
    session_summarize: bool = True
    episode_search_enabled: bool = True

    # Generative Agents-style reflection
    reflection_enabled: bool = True
    reflection_threshold: float = 1.0  # sum of importance scores to trigger reflection
    reflection_min_interval_hours: float = 1.0

    # Mental Model abstraction
    mental_model_enabled: bool = True
    mental_model_min_samples: int = 3

    # Retrieval composite scoring weights
    retrieval_recency_weight: float = 0.3
    retrieval_importance_weight: float = 0.3
    retrieval_relevance_weight: float = 0.4
    retrieval_rrf_k: float = 5.0  # RRF k parameter for memory search relevance scoring

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

    # Auto-capture
    auto_capture_enabled: bool = False
    auto_capture_interval: int = 300
    auto_capture_max_memories: int = 10

    # Memory enrichment
    memory_enrichment_enabled: bool = False
    memory_enrichment_auto_run: bool = False
    memory_enrichment_interval: int = 60
    memory_enrichment_llm: str = ""
    memory_enrichment_prompt_template: str = ""
    memory_enrichment_summary_granularity: str = "medium"
    memory_enrichment_provider: str = ""
    memory_enrichment_model: str = ""
    memory_enrichment_base_url: str = ""
    memory_enrichment_min_chars: int = 100

    # Forgetting
    forgetting_enabled: bool = False
    forgetting_trigger_threshold: int = 100
    forgetting_forget_ratio: float = 0.2
    forgetting_forget_strength: float = 0.5
    forgetting_decay_interval_seconds: int = 86400  # 24h default
    forgetting_min_strength: float = 0.1

    # MemoRAG
    memorag_chunk_size: int = 512
    memorag_chunk_overlap: int = 64
    memorag_top_k: int = 5
    memorag_similarity_threshold: float = 0.7
    memorag_enabled: bool = False
    memorag_snapshot_interval_hours: int = 24

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
