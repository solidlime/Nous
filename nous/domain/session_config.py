"""セッション管理設定 — SessionConfig.

ChatConfig から分割された、セッション管理・リフレクション・メモリ拡張・
音声・忘却に関する設定を保持する。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from nous.domain.value_objects import normalize_importance

VOICE_EMOTION_MODES = ("off", "anchor", "llm")


class SessionConfig(BaseModel):
    """セッション管理・メモリ設定。"""

    # 基本設定
    system_prompt: str = Field(default="", description="LLMに常に与えるシステムプロンプト。空欄でペルソナ既定を使います。")
    language: str = Field(default="ja", description="応答の表示言語。")  # "ja" | "en" | "zh" | "ko" | "auto"
    debug_mode: bool = Field(default=False, description="詳細ログを出力するデバッグモード。")
    show_message_timestamps: bool = Field(default=False, description="チャットメッセージにタイムスタンプを表示します。")  # チャットメッセージにタイムスタンプを表示
    session_summarize: bool = Field(default=True, description="セッション終了時に会話を要約して保存します。")
    episode_search_enabled: bool = Field(default=True, description="過去の会話エピソードも検索対象に含めます。")

    # Generative Agents-style reflection
    reflection_enabled: bool = Field(default=True, description="会話を振り返り、気づきや傾向を自動抽出します。")
    reflection_threshold: float = Field(default=1.0, description="リフレクションを発火する重要度の合計しきい値。")  # sum of importance scores to trigger reflection
    reflection_min_interval_hours: float = Field(default=1.0, description="リフレクションを実行する最小間隔（時間）。")

    # Mental Model abstraction
    mental_model_enabled: bool = Field(default=True, description="ユーザーの性格・好みのモデルを自動構築します。")
    mental_model_min_samples: int = Field(default=3, description="モデル更新に必要な最小サンプル数。")

    # Retrieval composite scoring weights
    retrieval_recency_weight: float = Field(default=0.3, description="記憶検索で新しさを重視する重み。")
    retrieval_importance_weight: float = Field(default=0.3, description="記憶検索で重要度を重視する重み。")
    retrieval_relevance_weight: float = Field(default=0.4, description="記憶検索で関連性を重視する重み。")
    # リフレクション記憶の無関係想起対策 (MemGPT archival 分離相当):
    # 検索複合スコアの降格係数 (1.0 で無効) と無条件注入のベクトル類似閾値 (0.0 で無効)
    reflection_retrieval_penalty: float = Field(default=0.5, description="リフレクション記憶を通常想起で降格する係数（1.0で無効）。")
    reflection_injection_min_similarity: float = Field(default=0.45, description="リフレクションを無条件注入する最低類似度。")
    # 注入候補の相対閾値マージン: sim >= (max_sim - margin) AND sim >= floor
    # (絶対閾値では関連/無関内省のコサイン分布が重なるため、集合内の相対選択で分離)
    reflection_injection_margin: float = Field(default=0.08, description="注入候補を選ぶ相対マージン。")

    @field_validator("reflection_retrieval_penalty")
    @classmethod
    def _clamp_reflection_penalty(cls, v: float) -> float:
        return max(0.1, min(1.0, v))

    @field_validator("reflection_injection_min_similarity")
    @classmethod
    def _clamp_reflection_similarity(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("reflection_injection_margin")
    @classmethod
    def _clamp_reflection_margin(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    # Voice / TTS settings (TE04)
    voice_enabled: bool = Field(default=False, description="音声合成（TTS）を有効にします。")
    voice_auto_play: bool = Field(default=False, description="AIの応答を自動で読み上げます。")
    voice_emotion_link: bool = Field(default=True, description="AIの感情を声に反映します。")
    voice_model: str = Field(default="", description="使用する声質（話者名）。")
    voice_url: str = Field(default="", description="TTSサーバーのURL。")
    voice_volume: float = Field(default=1.0, description="読み上げの音量（0〜1）。")
    voice_speed: float = Field(default=1.0, description="読み上げの速度（0.25〜4.0）。")
    voice_streaming: bool = Field(default=True, description="送信中の応答を文単位で逐次読み上げます。")
    # Irodori advanced TTS parameters
    irodori_num_steps: int = Field(default=30, description="音声生成の推論ステップ数。高いほど高品質・低速。")
    irodori_cfg_scale_text: float = Field(default=3.2, description="テキストへの忠実度（CFGスケール）。")
    irodori_cfg_scale_speaker: float = Field(default=5.0, description="話者への忠実度（CFGスケール）。")
    irodori_cfg_scale_caption: float = Field(default=4.2, description="感情キャプションへの忠実度（CFGスケール）。")
    irodori_chunk_min_chars: int = Field(default=85, description="音声を分割する最小文字数。")
    irodori_seed: int = Field(default=0, description="音声生成の乱数シード。0でランダム。")
    # Irodori LLM emotion caption
    irodori_caption_llm_enabled: bool = Field(default=False, description="感情キャプション生成にLLMを使います。")
    irodori_caption_llm_model: str = Field(default="", description="感情キャプション生成に使うモデル。空欄でメインのモデル。")  # empty = use persona's configured model
    # 感情の声への反映モード: "off" | "anchor" | "llm"。
    # 旧2ブール値 (voice_emotion_link / irodori_caption_llm_enabled) の上位概念。
    # 旧設定ファイルには本キーが無いので before-validator で旧値から導出する。
    voice_emotion_mode: str = Field(default="anchor", description="感情の声への反映方法（off / anchor / llm）。")

    # Memory enrichment
    memory_enrichment_enabled: bool = Field(default=False, description="記憶の重要度・関係性を自動で強化します。")
    memory_enrichment_auto_run: bool = Field(default=False, description="記憶強化を自動実行します。")
    memory_enrichment_interval: int = Field(default=60, description="記憶強化を実行する間隔（秒）。")
    memory_enrichment_model: str = Field(default="", description="記憶強化に使うモデル。空欄でメインのモデル。")
    memory_enrichment_prompt_template: str = Field(
        default=(
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
        "   - type: 関係タイプ（knows, works_with, manages, created, located_in, part_of, related_to, summarizes のいずれか）\n"
        "   - confidence: 抽出の確信度（0.0〜1.0）\n\n"
        "出力は必ず以下のJSON形式に従ってください：\n"
        '{"importance": 0.5, "relations": [{"source": "entity1", "target": "entity2", "type": "knows", "confidence": 0.9}]}\n\n'
        "関係が見つからない場合は relations を空配列にしてください。"
        ),
        description="記憶強化に使うプロンプトのテンプレート。",
    )

    # Brain simulation (cross-lane contract: key names / defaults are fixed —
    # lane3 UI consumes them verbatim; see docs/superpowers/plans/2026-09-06-brain-simulation.md)
    brain_enrich_auto_run: bool = Field(default=False, description="脳シミュレーションによる記憶強化を自動実行します。")
    brain_enrich_interval_seconds: int = Field(default=60, description="記憶強化の実行間隔（秒）。")
    brain_enrich_batch_limit: int = Field(default=5, description="1回の記憶強化で処理する最大件数。")
    brain_novelty_sim_threshold: float = Field(default=0.75, description="新規性判定に使う類似度しきい値。")
    brain_novelty_importance_threshold: float = Field(default=0.6, description="新規性判定に使う重要度しきい値。")
    brain_novelty_stability_multiplier: float = Field(default=2.0, description="新規記憶の安定度に掛ける倍率。")
    brain_emotion_gain_k: float = Field(default=0.5, description="感情による記憶強化の利得係数。")
    brain_rif_suppression_rho: float = Field(default=0.05, description="検索誘発性忘却の抑制率。")
    brain_link_separation_threshold: float = Field(default=0.75, description="記憶リンクを分離する類似度しきい値。")
    brain_graph_flash_enabled: bool = Field(default=True, description="記憶グラフのシナプス発火を可視化します。")
    # Idle-gated REM drain (persistent enrichment queue)
    brain_idle_after_seconds: int = Field(default=120, description="無操作がこの秒数続いたら記憶強化を開始します。")
    brain_min_batch_size: int = Field(default=3, description="記憶強化を開始する最小たまり件数。")
    brain_max_defer_seconds: int = Field(default=3600, description="記憶強化を遅延できる最大秒数。")
    # Dedicated LLM for the brain simulator (OFF = reuse the chat 4-piece set)
    brain_llm_dedicated: bool = Field(default=False, description="脳シミュレーション専用のLLMを使います。")
    brain_llm_provider: str = Field(default="", description="脳専用LLMのプロバイダー。")
    brain_llm_model: str = Field(default="", description="脳専用LLMのモデル名。")
    brain_llm_base_url: str = Field(default="", description="脳専用LLMの接続先URL。")
    brain_llm_api_key: str = Field(default="", description="脳専用LLMのAPIキー。")
    # Dedicated LLM for the item (inventory) extractor — split from the context
    # extractor (spec F). OFF = reuse extract_model / the chat 4-piece set.
    item_llm_dedicated: bool = Field(default=False, description="アイテム抽出専用のLLMを使います。")
    item_llm_provider: str = Field(default="", description="アイテム抽出専用LLMのプロバイダー。")
    item_llm_model: str = Field(default="", description="アイテム抽出専用LLMのモデル名。")
    item_llm_base_url: str = Field(default="", description="アイテム抽出専用LLMの接続先URL。")
    item_llm_api_key: str = Field(default="", description="アイテム抽出専用LLMのAPIキー。")
    # REM 独り言 (drain バッチ完走時に LLM 1 call で生成・session_events 保存)
    brain_monologue_enabled: bool = Field(default=True, description="記憶強化の完了時に独り言を生成します。")
    # 内省エンジン (drain 後の単一 LLM 呼び出し: 独り言＋逸脱判定＋反省＋感情/身体)
    brain_introspection_enabled: bool = Field(default=True, description="独り言・反省・感情をまとめて内省する機能を有効にします。")
    # 脳専用 reasoning トグル (chat の reasoning_enabled/effort とは独立)。
    # ON で脳側呼び出し (内省・記憶強化) に reasoning_effort を渡す。OFF は None
    # (openai_compat が openrouter + effort=None で reasoning を無効化する)。
    brain_reasoning_enabled: bool = Field(default=False, description="脳シミュレーションの呼び出しで推論を使います。")
    brain_reasoning_effort: str = Field(default="medium", description="脳シミュレーションの推論の深さ。")
    # 脳側呼び出しの共通 max_tokens（下限の意味: reasoning ON 時は openai_compat が
    # max(max_tokens, budget+1024) に引き上げる）。enricher / introspection で共有。
    brain_max_tokens: int = Field(default=2048, description="脳シミュレーション呼び出しの最大トークン数。")
    # 自発的内省: 誰も話しかけてこない静かな時間に記憶と現在状態から独り言を産出。
    # 発火間隔は brain.introspection / brain.introspection_spontaneous 両種別の
    # 最新タイムスタンプから interval_hours 以上経過で判定（worker 側ガード）。
    brain_spontaneous_enabled: bool = Field(default=True, description="誰も話しかけない時間に自発的な内省を生成します。")
    brain_spontaneous_interval_hours: int = Field(default=1, description="自発的内省を実行する間隔（時間）。")
    # 内省プロンプト上書き (空文字 = コード内デフォルトを使用)。
    # プレースホルダ: {persona} {current_state} {memory_texts} {persona_identity}
    #   + ターン駆動のみ {recent_turns}。欠落があるとデフォルトへ自動フォールバック。
    brain_introspection_prompt: str = Field(default="", description="内省プロンプトの上書き。空欄で既定を使います。")
    brain_spontaneous_prompt: str = Field(default="", description="自発的内省プロンプトの上書き。空欄で既定を使います。")

    @field_validator("brain_reasoning_effort")
    @classmethod
    def _clamp_brain_reasoning_effort(cls, v: str) -> str:
        from nous.domain.provider_config import REASONING_EFFORTS

        return v if v in REASONING_EFFORTS else "medium"  # 不正値は既存 clamp と同一形式

    @field_validator("brain_max_tokens")
    @classmethod
    def _clamp_brain_max_tokens(cls, v: int) -> int:
        # 下限 256: interpretation エラー防止の実用下限（provider 側 1..32768 と同型）
        return max(256, min(32768, v))

    @field_validator("brain_spontaneous_interval_hours")
    @classmethod
    def _clamp_brain_spontaneous_interval(cls, v: int) -> int:
        return max(1, min(72, v))

    # Forgetting
    forgetting_enabled: bool = Field(default=False, description="重要度の低い記憶を時間経過で減衰・削除します。")
    forgetting_trigger_threshold: int = Field(default=100, description="忘却処理を開始する記憶数のしきい値。")
    forgetting_forget_ratio: float = Field(default=0.2, description="1回の忘却で対象にする記憶の割合。")
    forgetting_forget_strength: float = Field(default=0.5, description="忘却時に低下させる重要度の量。")
    forgetting_decay_interval_seconds: int = Field(default=3600, description="重要度を減衰させる処理の実行間隔（秒）。")  # 1h sweep — 減衰は経過時間依存なので sweep は平滑性にのみ影響
    forgetting_min_strength: float = Field(default=0.1, description="これを下回った記憶を忘却対象にします。")

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
