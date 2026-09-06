"""セッション管理設定 — SessionConfig.

ChatConfig から分割された、セッション管理・リフレクション・メモリ拡張・
音声・忘却に関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator

from nous.domain.value_objects import normalize_importance

VOICE_EMOTION_MODES = ("off", "anchor", "llm")


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
    # 感情の声への反映モード: "off" | "anchor" | "llm"。
    # 旧2ブール値 (voice_emotion_link / irodori_caption_llm_enabled) の上位概念。
    # 旧設定ファイルには本キーが無いので before-validator で旧値から導出する。
    voice_emotion_mode: str = "anchor"

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

    # Brain simulation (cross-lane contract: key names / defaults are fixed —
    # lane3 UI consumes them verbatim; see docs/superpowers/plans/2026-09-06-brain-simulation.md)
    brain_enrich_auto_run: bool = False
    brain_enrich_interval_seconds: int = 60
    brain_enrich_batch_limit: int = 5
    brain_novelty_sim_threshold: float = 0.75
    brain_novelty_importance_threshold: float = 0.6
    brain_novelty_stability_multiplier: float = 2.0
    brain_emotion_gain_k: float = 0.5
    brain_rif_suppression_rho: float = 0.05
    brain_link_separation_threshold: float = 0.75
    brain_graph_flash_enabled: bool = True

    # Forgetting
    forgetting_enabled: bool = False
    forgetting_trigger_threshold: int = 100
    forgetting_forget_ratio: float = 0.2
    forgetting_forget_strength: float = 0.5
    forgetting_decay_interval_seconds: int = 86400  # 24h default
    forgetting_min_strength: float = 0.1

    @field_validator("voice_emotion_mode")
    @classmethod
    def _clamp_emotion_mode(cls, v: str) -> str:
        return v if v in VOICE_EMOTION_MODES else "anchor"

    @model_validator(mode="before")
    @classmethod
    def _derive_emotion_mode(cls, data):
        """旧2ブール値しかない入力から voice_emotion_mode を導出する (移行用)。"""
        if isinstance(data, dict) and "voice_emotion_mode" not in data:
            data = dict(data)
            link = data.get("voice_emotion_link", True)
            llm = data.get("irodori_caption_llm_enabled", False)
            if llm and link:
                data["voice_emotion_mode"] = "llm"
            elif link:
                data["voice_emotion_mode"] = "anchor"
            else:
                # link OFF + llm ON の死に設定は、実際に聞こえていた通り "off" に倒す
                data["voice_emotion_mode"] = "off"
        return data

    @field_validator("voice_speed")
    @classmethod
    def _clamp_voice_speed(cls, v: float) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 1.0
        import math

        if math.isnan(f) or math.isinf(f):
            return 1.0
        return max(0.25, min(4.0, f))

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
