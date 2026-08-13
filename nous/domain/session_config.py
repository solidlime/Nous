"""セッション管理設定 — SessionConfig.

ChatConfig から分割された、セッション管理・リフレクション・メモリ拡張・
音声・忘却・MemoRAGに関する設定を保持する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from nous.domain.value_objects import normalize_importance


class AvatarConfig(BaseModel):
    """PNGTuberアバター設定（R6）。既定は無効（後方互換のため既存 config.json に影響しない）。"""

    enabled: bool = False
    panel_position: Literal["top", "bottom"] = "top"
    mouth_mode: Literal["analyser", "toggle"] = "analyser"
    panel_width: int = 220

    @field_validator("panel_width")
    @classmethod
    def _clamp_panel_width(cls, v: int) -> int:
        return max(80, min(800, v))


class SessionConfig(BaseModel):
    """セッション管理・メモリ設定。"""

    # 基本設定
    system_prompt: str = ""
    language: str = "ja"  # "ja" | "en" | "zh" | "ko" | "auto"
    debug_mode: bool = False
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
    # Irodori LLM emotion caption
    irodori_caption_llm_enabled: bool = False
    irodori_caption_llm_model: str = ""  # empty = use persona's configured model

    # Auto-capture
    auto_capture_enabled: bool = False
    auto_capture_interval: int = 300
    auto_capture_max_memories: int = 10

    # Memory enrichment
    memory_enrichment_enabled: bool = False
    memory_enrichment_auto_run: bool = False
    memory_enrichment_interval: int = 60
    memory_enrichment_model: str = ""
    memory_enrichment_prompt_template: str = (
        "あなたは記憶分析アシスタントです。与えられた記憶テキストを分析し、以下の2つをJSON形式で出力してください：\n\n"
        "1. **importance**: この記憶の重要度を0.0（全く重要でない）〜1.0（極めて重要）の浮動小数点数で評価してください。\n"
        "   - 0.0-0.3: 日常的な些事、一時的な感情\n"
        "   - 0.4-0.6: 通常の出来事、一般的な情報\n"
        "   - 0.7-0.8: 重要な出来事、強い感情を伴う体験\n"
        "   - 0.9-1.0: 人生を変える出来事、核となる記憶\n\n"
        "2. **relations**: テキスト内のエンティティ（人名、場所、概念など）間の関係性を抽出してください。\n"
        "   各関係は以下の形式です：\n"
        "   - source: 関係の主体（エンティティ名）\n"
        "   - target: 関係の対象（エンティティ名）\n"
        "   - type: 関係タイプ（knows, works_with, manages, created, located_in, part_of, related_to のいずれか）\n"
        "   - confidence: 抽出の確信度（0.0〜1.0）\n\n"
        "出力は必ず以下のJSON形式に従ってください：\n"
        '{"importance": 0.5, "relations": [{"source": "entity1", "target": "entity2", "type": "knows", "confidence": 0.9}]}\n\n'
        "関係が見つからない場合は relations を空配列にしてください。"
    )

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

    # PNGTuber avatar (R6)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)

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
