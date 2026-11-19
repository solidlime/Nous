from __future__ import annotations

import functools
import logging
import os
import re
from pathlib import Path
from typing import Self

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ペルソナ名はディレクトリ1セグメント。実データ領域のパスに使うのでここで絞る。
_PERSONA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class EmbeddingConfig(BaseModel):
    """Embedding model configuration.

    ``dimensions``: MRL (Matryoshka) 切り詰め次元。ruri-v3 系は先頭 N 次元だけで
    も有効な埋め込みになるよう学習されているため、切り詰め後に L2 再正規化して使う。
    ``None`` なら graph 出力の全次元（ruri-v3-70m は 384）。既定 256 は
    既存 Qdrant コレクションの次元と一致させるための確定値。
    """

    model: str = "mochiya98/ruri-v3-70m-onnx"
    tokenizer: str = "cl-nagoya/ruri-v3-70m"
    dimensions: int | None = Field(default=256, gt=0)
    device: str = "cpu"
    batch_size: int = 32


class RerankerConfig(BaseModel):
    """Reranker model configuration."""

    model: str = "hotchpotch/japanese-reranker-xsmall-v2"
    enabled: bool = True


class SearchConfig(BaseModel):
    """検索パイプライン設定（env: NOUS_SEARCH__RERANK_ENABLED 等）。"""

    # item 5: FTS OR-fallback に渡す bm25 バー（dominantTokenKind 別、正の大きさ）。
    # 候補は bm25 rank（負値）<= -bar のとき通過する。実測推奨は bigram=2.0 / word=2.0
    # （research/nous-search-eval-20260928/item5_threshold_design.md）。
    # env: NOUS_SEARCH__INJECTION_MAX_BM25='{"bigram": 2.5, "word": 2.5}'（JSON）。
    injection_max_bm25: dict[str, float] = Field(default_factory=lambda: {"bigram": 2.0, "word": 2.0})

    # Cross-encoder rerank 段の有効化。既定 False。
    # 部分 rerank（上位 _RERANK_CANDIDATES 件のみ）は cross-encoder スコアと未 rerank の
    # RRF スコアを同一キーで再ソートするため順位を壊す（実測: all-term MRR 1.0→0.8704）。
    # 無効化しても reranker のロード経路（reranker.enabled）は壊さない。
    rerank_enabled: bool = False

    # 記憶鮮度の指数減衰係数（time_utils.get_recency_boost の λ）。
    # 0.5 = 既定の「日ごとに半減」相当。act/expert 向け。
    recency_lambda: float = Field(default=0.5, gt=0.0, le=1.0)


class QdrantConfig(BaseModel):
    """Qdrant vector store configuration."""

    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection_prefix: str = "memory_"


class ServerConfig(BaseModel):
    """HTTP/MCP server configuration."""

    host: str = "0.0.0.0"  # nosec B104 - intentional for Docker deployment; use 127.0.0.1 for localhost-only
    port: int = 26262


def _parse_str_list(v: object) -> list[str]:
    """Accept a list, JSON array string, or comma-separated string."""
    if isinstance(v, list):
        return [str(s).strip() for s in v if str(s).strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        if s.startswith("["):
            import json

            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                logger.debug("settings: JSON list parse failed, falling back to comma-split: %r", s)
        return [p.strip() for p in s.split(",") if p.strip()]
    return []


class McpSecurityConfig(BaseModel):
    """MCP DNS-rebinding protection allowlists (applied on restart)."""

    allowed_hosts: list[str] = ["nous:*", "localhost:*", "127.0.0.1:*", "[::1]:*"]
    """Allowed Host header values ('*' suffix matches any port).
    Env ``NOUS_MCP_SECURITY__ALLOWED_HOSTS`` accepts a JSON array.
    WebUI stores comma-separated text."""

    allowed_origins: list[str] = ["http://nous:*", "http://localhost:*", "http://127.0.0.1:*"]
    """Allowed Origin header values. Same format as allowed_hosts."""

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def split_str_list(cls, v: object) -> object:
        return _parse_str_list(v)


class LLMConfig(BaseModel):
    """共有 LLM 接続設定（内省 / 矛盾判定 / 記憶抽出が使う）。"""

    enabled: bool = True
    provider: str = "openrouter"
    api_key: str | None = None
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"
    # openai_compat のリクエストタイムアウト。低速プロバイダで詰まる筆頭（D2-4）。
    timeout_seconds: int = Field(default=60, gt=0)
    # 画像入力可能判定のモデル名リスト（旧 openai_compat._VISION_MODEL_PREFIXES の Settings 外部化。正はここ）。
    vision_models: list[str] = Field(
        default_factory=lambda: ["gpt-4o", "gpt-4-turbo", "gpt-4-vision", "o1", "o3", "o4-mini"]
    )
    non_vision_models: list[str] = Field(default_factory=lambda: ["gpt-3.5"])
    # 記憶抽出 LLM の max_tokens（コスト直結 — D2-15）。
    extraction_max_tokens: int = Field(default=8192, gt=0)

    def get_effective_api_key(self, settings: Settings) -> str:
        """Return API key, falling back to global Settings keys."""
        # 1. Explicit memory_enrichment.api_key
        if self.api_key:
            return self.api_key

        # 2. Provider-matched global Settings key
        if self.provider == "openrouter" and settings.openrouter_api_key:
            return settings.openrouter_api_key
        if self.provider == "anthropic" and settings.anthropic_api_key:
            return settings.anthropic_api_key
        if self.provider == "openai" and settings.openai_api_key:
            return settings.openai_api_key
        if self.provider == "google" and settings.google_api_key:
            return settings.google_api_key
        if self.provider == "opencode_go" and settings.opencode_go_api_key:
            return settings.opencode_go_api_key

        # 3. RuntimeConfigManager fallback (hot-reload overrides)
        from nous.config.runtime_config import RuntimeConfigManager

        key_name = f"{self.provider}_api_key"
        value, _ = RuntimeConfigManager().get_effective_value("api_keys", key_name)
        if value:
            return value

        # 4. Backward compat: legacy env vars without NOUS_ prefix
        _legacy_env_keys = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GEMINI_API_KEY",
            "opencode_go": "OPENCODE_GO_API_KEY",
        }
        env_var = _legacy_env_keys.get(self.provider, "")
        return os.environ.get(env_var, "")


class IrodoriAdvancedParams(BaseModel):
    """Irodori-TTS top-level irodori options (num_steps / cfg_* / chunking / caption / seed)."""

    num_steps: int = 30
    """Inference steps. Range: 10-50. Higher = better quality, slower."""

    cfg_scale_text: float = 3.2
    """Text adherence. Range: 1.0-5.0."""

    cfg_scale_speaker: float = 5.0
    """Reference voice fidelity. Range: 1.0-8.0."""

    cfg_scale_caption: float = 4.2
    """Emotion/style strength. Range: 1.0-8.0."""

    chunk_min_chars: int = 85
    """Min chars per chunk for long text. Range: 30-200 (default 85).

    v4.0 (audit L5): このノブは 3 箇所に現れていた（engine 層の既定・chat 層の
    既定 session_config.ChatConfig.irodori_chunk_min_chars・tts.py の getattr
    fallback）。現在は **85 が単一の正** であり、engine 層の既定も同じ 85 に統一
    している（tests/unit/test_config_defaults.py の lock-in テストで固定）。

    優先順位（"設定優先順位表" の 1 行）: persona の chat 設定（UI スライダー）
    > chat 層の既定 85 > この engine 層の既定 85。環境変数
    NOUS_IRODORI__CHUNK_MIN_CHARS は engine 層（直接 IrodoriConfig を組む経路）
    にのみ作用し、chat TTS は persona 設定値を使う。

    参考: 40（改行の間を保つための小さめチャンク）は SSE ストリーミング
    （docs/archive/superpowers/specs/2026-09-05-tts-sse-unification-design.md）で
    検討された値だが、既定として採用はしていない。変更する場合は chat 層・
    engine 層・UI 表示を同時に動かすこと。
    """

    first_sentence_chunk_min_chars: int = 1
    """First-sentence fast-path chunk threshold for SSE. Range: 1-200."""

    seed: int | None = None
    """Random seed. None = random. Set to int for deterministic output."""


class IrodoriConfig(BaseModel):
    """Irodori-TTS connection configuration — provider settings only.
    Env var: ``NOUS_IRODORI__URL`` (default: http://localhost:8088)
    """

    url: str = "http://localhost:8088"
    """Irodori-TTS-Server base URL (e.g. http://192.168.50.150:8088). /v1 prefix is added automatically."""

    voice: str = "default"
    """Default voice name."""

    model: str = "irodori-tts"
    """TTS model name (fixed for Irodori)."""

    timeout_seconds: int = 30
    """Generation timeout in seconds."""

    retry_count: int = 3
    """音声生成失敗時のリトライ回数（voice/irodori.py の固定値 → 設定化）。"""

    health_timeout_seconds: int = 5
    """GET /v1/models 疎通確認の httpx タイムアウト（旧 irodori.py/tts.py の二重実装をこの1キーへ統一）。"""

    advanced: IrodoriAdvancedParams = IrodoriAdvancedParams()


class CorsConfig(BaseModel):
    """CORS (Cross-Origin Resource Sharing) configuration.

    Secure defaults: explicit localhost dev origins with credentials allowed.
    A wildcard (``"*"``) is only used when explicitly set via
    ``NOUS_CORS_ALLOWED_ORIGINS`` (credentials are then forced off).
    """

    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    """Allowed origins. Env var ``NOUS_CORS__ALLOWED_ORIGINS`` accepts JSON array
    (e.g. ``'["http://a.com","http://b.com"]'``) **or** comma-separated string
    (e.g. ``http://a.com,http://b.com``).
    Default: explicit localhost dev origins. Production should set explicit origins."""

    allow_credentials: bool = True
    allow_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers: list[str] = ["Authorization", "Content-Type", "X-Persona"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_comma_separated(cls, v: object) -> object:
        """Allow comma-separated string as input (for non-JSON env vars)."""
        if isinstance(v, str):
            # Try JSON first
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                logger.debug("settings: allowed_origins JSON parse failed, falling back to comma-split: %r", v)
            # Fallback: comma-separated
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @model_validator(mode="after")
    def _enforce_credentials_compatibility(self) -> Self:
        """ワイルドカード origins × allow_credentials=True はブラウザに拒否されるため強制無効化する。"""
        if "*" in self.allowed_origins and self.allow_credentials:
            import logging

            logging.getLogger(__name__).warning(
                "CORS: allowed_origins contains '*' with allow_credentials=True — "
                "browsers reject this combination. Forcing allow_credentials=False."
            )
            self.allow_credentials = False
        return self


class WikiConfig(BaseModel):
    """ドリーミング (wiki 編纂) worker の設定（wiki_worker.py）。

    計画書: docs/archive/superpowers/plans/2026-11-07-wiki-dreaming.md §4.2。
    既定 disabled — 有効化は NOUS_WIKI__ENABLED=true。
    """

    enabled: bool = False
    interval_seconds: int = 86400  # 24h cycle
    # 毎日この時刻（ローカル TZ）に実行する。負値（-1）で旧来の interval 方式。
    # 範囲外だと _next_delay の now.replace() が ValueError を投げ、worker が
    # 無言で永久停止するので pydantic 側で潰す。
    run_at_hour: int = Field(default=3, ge=-1, le=23)
    # run_at_hour を解釈するタイムゾーン。コンテナが UTC で動いていても「03:00 JST」の
    # 意味を保つため既定は Asia/Tokyo（time_utils._DEFAULT_TZ と同じ）。UTC 運用したい
    # 場合は NOUS_WIKI__RUN_AT_TZ=UTC を明示する。
    run_at_tz: str = "Asia/Tokyo"

    @field_validator("run_at_tz")
    @classmethod
    def _validate_run_at_tz(cls, value: str) -> str:
        """未知の TZ 名は起動時に落とす（worker が無言で永久停止するのを防ぐ）。"""
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception as e:
            raise ValueError(f"unknown timezone {value!r}: {e}") from e
        return value

    topics_per_cycle: int = 2  # 1 cycle で編纂する topic 数
    # 日記（前日 JST の記憶を 1 ページに）。専用ストレージは作らない（wiki ページ）。
    journal_enabled: bool = True
    journal_max_sources: int = 60  # 日記 1 ページの材料上限
    # その日の営み（pi の turn.completed / session.started）も日記の材料にする。
    # 記憶は要点抽出後なので「何をしていたか」が落ちる。生ログから活動を拾う。
    journal_include_activity: bool = True
    journal_activity_max_events: int = 400  # session_events を型ごとに何件まで読むか（日で絞った後の上限）
    journal_activity_chars: int = 12000  # 営みの材料に使う合計文字数の上限
    # 日記生成後に感情・体調を 1 回反映する（LLM 呼び出し +1）。
    journal_apply_state: bool = True
    # 日記の「活動」に、人物設定（chat config の system_prompt + 自己像ブロック）から
    # 起こした暮らしを混ぜる（研究・料理・手入れなど）。記憶には残さず日記の材料だけ。
    # 設定が読めない人物は何もしない（生活をでっち上げない）。LLM 呼び出し +1/日。
    life_enabled: bool = True
    life_events_per_day: int = 3
    # 日記から「明日やること」を起こし、指定時刻に自分で走る予定（agent:task）として
    # 登録する（#63）。実行は ProspectiveWorker の毎時照合。
    journal_tomorrow_tasks: bool = True
    journal_tomorrow_max: int = 3
    # 矛盾整理（#39/#55）。編纂プロンプトの conflicts で拾い（追加呼び出しなし）、
    # 解消は resolved:true で質問を閉じる。記憶層の週次掃除は Zero Inbox で退役（#54）。
    conflict_check_enabled: bool = True  # wiki 編纂プロンプトに conflicts/questions を要求するか
    max_open_questions: int = 20  # 未解決の問いの上限（正規化キーで重複は 1 件、#55）
    # 自走調査（#40）。登録済み MCP ツールがある時だけ動く（無ければ何もしない）。
    # mcp-hub の 3 段メタ呼び出しに未対応のため既定は無効（#53）。
    research_enabled: bool = False
    max_research_per_cycle: int = 3  # 1 サイクルで調べる質問数
    research_max_tool_calls: int = 3  # 1 質問あたりのツール実行上限
    max_memories_per_topic: int = 40
    max_sources_per_page: int = 40  # ページ 1 枚の sources 上限（超過は分割を強制）
    # この日数以上更新されていないページは編纂で必ず改訂させる（放置ページ対策）。
    stale_days: int = 7
    max_page_bytes: int = 8192
    # topic 編纂に必要な記憶の最低件数（不足なら topic をスキップ）。
    min_topic_memories: int = 3
    # Worker ループの待機/エラー再試行周期。
    worker_retry_seconds: int = 60
    worker_error_retry_seconds: int = 1800
    provider: str = "openrouter"
    api_key: str | None = None
    model: str = "openai/gpt-4o-mini"
    base_url: str = "https://openrouter.ai/api/v1"

    def get_effective_api_key(self, settings: Settings) -> str:
        """API key 解決（LLMConfig.get_effective_api_key と同型）。"""
        if self.api_key:
            return self.api_key
        if self.provider == "openrouter" and settings.openrouter_api_key:
            return settings.openrouter_api_key
        if self.provider == "anthropic" and settings.anthropic_api_key:
            return settings.anthropic_api_key
        if self.provider == "openai" and settings.openai_api_key:
            return settings.openai_api_key
        if self.provider == "google" and settings.google_api_key:
            return settings.google_api_key
        if self.provider == "opencode_go" and settings.opencode_go_api_key:
            return settings.opencode_go_api_key

        from nous.config.runtime_config import RuntimeConfigManager

        key_name = f"{self.provider}_api_key"
        value, _ = RuntimeConfigManager().get_effective_value("api_keys", key_name)
        if value:
            return str(value)

        _legacy_env_keys = {
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GEMINI_API_KEY",
            "opencode_go": "OPENCODE_GO_API_KEY",
        }
        env_var = _legacy_env_keys.get(self.provider, "")
        return os.environ.get(env_var, "")


class PluginConfig(BaseModel):
    """Plugin API configuration — default OFF for security.

    Must be explicitly enabled AND configured with an api_key for access.
    """

    enabled: bool = False
    """DEFAULT OFF — must be explicitly enabled for plugin API access.
    Set ``NOUS_PLUGIN__ENABLED=true`` to enable."""

    api_key: str = ""
    """API key required for Bearer token authentication.
    Must be a non-empty string when enabled.
    Set ``NOUS_PLUGIN__API_KEY=<strong_key>``."""


# 多段 curiosity の予算上限。ExplorerConfig の clamp だけが使う。
# （explorer 本体は 2026-11-09 の #35 で削除済み。設定と上限だけが残っている）
MAX_TOOL_CALLS_CAP = 10


def clamp_max_tool_calls(v: int) -> int:
    """ExplorerConfig.max_tool_calls の唯一の正規化 (1..MAX_TOOL_CALLS_CAP)。"""
    return max(1, min(MAX_TOOL_CALLS_CAP, int(v)))


class ExplorerConfig(BaseModel):
    """アイドル時好奇心探索の設定。**読むコードは無い**（探索は #35 で削除）。

    env 互換（NOUS_EXPLORER__*）と UI の設定画面のために形だけ残している。
    復活させるなら消費側を先に書く。
    """

    enabled: bool = True
    # 多段リサーチ（mcp-hub の search_tools→execute_tool 等）で使う 1 探索あたりの
    # ツールコール予算。1..MAX_TOOL_CALLS_CAP にクランプ（暴走防止）。
    max_tool_calls: int = 5

    @field_validator("max_tool_calls")
    @classmethod
    def _clamp_max_tool_calls(cls, v: int) -> int:
        return clamp_max_tool_calls(v)


class MemoryConfig(BaseModel):
    """記憶ドメインのしきい値群（書き込み重複 / 相互相関 / mot 思考）。D4-1 統一済み。"""

    # 書き込み重複判定の semantic しきい値。hooks 側 0.85 と write_service 側 0.75 の
    # 不揃いを 0.85 に一本化（D2-1/D2-2）。上位互換: 0.75 で拾っていた 0.75-0.85 帯の
    # 類似記憶は弾かれるようになる。
    duplicate_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    # evolution_service の相互相関判定しきい値（corroboration / interference）。
    corroboration_min: float = Field(default=0.9, ge=0.0, le=1.0)
    interference_min: float = Field(default=0.85, ge=0.0, le=1.0)
    interference_max: float = Field(default=0.95, ge=0.0, le=1.0)
    # mot（自己思考痕跡）の減衰パラメータ。
    mot_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    mot_top_k: int = Field(default=3, ge=1)
    mot_corrosion_per_hour: float = Field(default=0.02, ge=0.0)
    mot_min_effective_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    mot_ttl_hours: int = Field(default=72, ge=1)


class McpClientConfig(BaseModel):
    """MCP クライアントのタイムアウト（http_client / stdio_client 共通）。"""

    request_timeout_seconds: int = Field(default=30, gt=0)


class WorkersConfig(BaseModel):
    """常駐 Worker の周期。全 worker ループ内で動的読みする（hot_reload 対応）。"""

    # proactive: 自発ターン（self-turn）の発生周期。
    proactive_interval_seconds: int = Field(default=1800, gt=0)
    # activity: ペルソナの暮らし営みの周期。
    activity_interval_seconds: int = Field(default=3600, gt=0)
    # prospective: cue の期限監視周期と、期限起点の最小待機秒。
    prospective_interval_seconds: int = Field(default=3600, gt=0)
    prospective_min_wait_seconds: float = Field(default=30.0, gt=0.0)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="NOUS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    server: ServerConfig = ServerConfig()
    mcp_security: McpSecurityConfig = Field(default_factory=McpSecurityConfig)
    plugin: PluginConfig = Field(default_factory=PluginConfig)
    # LLM provider API keys (shared across subsystems)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    google_api_key: str = ""  # env: NOUS_GOOGLE_API_KEY
    opencode_go_api_key: str = ""  # env: NOUS_OPENCODE_GO_API_KEY
    api_key: str = ""
    """HTTP Bearer credential (env ``NOUS_API_KEY``).

    Empty (default) is a documented dev pass-through: the Bearer token is
    treated as the persona name. When non-empty, strict mode applies —
    ``Authorization: Bearer <api_key>`` must match exactly, else HTTP 401.
    """

    embedding: EmbeddingConfig = EmbeddingConfig()
    reranker: RerankerConfig = RerankerConfig()
    search: SearchConfig = Field(default_factory=SearchConfig)
    qdrant: QdrantConfig = QdrantConfig()
    # env 互換のため名前据え置き: 本番 compose が NOUS_MEMORY_ENRICHMENT__* を設定している。
    # 中身は enrichment 廃止 (2026-11-08) 後も共有 LLM 接続設定として使う。
    memory_enrichment: LLMConfig = Field(default_factory=LLMConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    explorer: ExplorerConfig = Field(default_factory=ExplorerConfig)
    cors: CorsConfig = CorsConfig()
    irodori: IrodoriConfig = Field(default_factory=IrodoriConfig)
    # 記憶しきい値群（hooks/write_service 0.85 に一本化、evolution、mot）。
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    # MCP クライアントのタイムアウト（http_client / stdio_client 共通）。
    mcp_client: McpClientConfig = Field(default_factory=McpClientConfig)
    # 常駐 Worker の周期（proactive / activity / prospective）。
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    # ユーザーの agent 承認を待つ上限秒（sudo / 本体側承認フロー）。
    approval_timeout_seconds: int = Field(default=120, gt=0)
    timezone: str = "Asia/Tokyo"
    # 旧名 NOUS_SILENCE_HOURS も env 互換として受理する（名称は ChatConfig 側の
    # session_notes 静寂閾値との誤認防止のため分離 — oracle #11）。
    # pydantic-settings は validation_alias に env_prefix を付与しないため、
    # env 名はフルで列挙する。
    session_silence_hours: float = Field(
        default=6.0,
        validation_alias=AliasChoices(
            "session_silence_hours",
            "silence_hours",
            "NOUS_SESSION_SILENCE_HOURS",
            "NOUS_SILENCE_HOURS",
        ),
    )
    """``session_begin`` が「沈黙の間」の記憶を作る閾値（時間・kanban #37）。"""
    data_root: str = "./data"
    log_level: str = "INFO"
    default_persona: str | None = None  # 未読。将来のディスパッチ用に残っている
    contradiction_threshold: float = 0.85  # 未読。実効値は _check_duplicate の 0.75

    # NOTE: 重複検知の閾値は ``MemoryWriteService._check_duplicate`` の内部定数（0.75）が
    # 唯一の実効値。設定ノブは存在しない（v4.0 で未配線の duplicate_threshold を削除）。

    # Flat CORS origins env var (supports comma-separated; nested var
    # NOUS_CORS__ALLOWED_ORIGINS requires JSON array).  Parsed into
    # ``cors.allowed_origins`` via :meth:`_apply_cors_allowed_origins`.
    cors_allowed_origins_env: str = Field(
        default="",
        alias="NOUS_CORS_ALLOWED_ORIGINS",
    )

    @model_validator(mode="after")
    def apply_cors_allowed_origins(self) -> Self:
        """Parse NOUS_CORS_ALLOWED_ORIGINS (comma-separated) into cors.allowed_origins."""
        raw = self.cors_allowed_origins_env.strip()
        if raw:
            import json

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [s.strip() for s in raw.split(",") if s.strip()]
            if isinstance(parsed, str):
                parsed = [parsed]
            self.cors.allowed_origins = parsed
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        from zoneinfo import available_timezones

        if v not in available_timezones():
            raise ValueError(f"Invalid timezone: '{v}'. Use a valid IANA timezone (e.g., 'Asia/Tokyo').")
        return v

    @field_validator("contradiction_threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"Threshold must be between 0.0 and 1.0, got {v}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return upper

    @computed_field
    @property
    def data_dir(self) -> str:
        """DEPRECATED: Use persona_dir or persona_path() instead. 旧互換用。"""
        return f"{self.data_root}/persona"

    @computed_field
    @property
    def persona_dir(self) -> str:
        """ペルソナ別データ格納ディレクトリ: {data_root}/persona"""
        return f"{self.data_root}/persona"

    def persona_path(self, persona_name: str) -> str:
        """特定ペルソナのデータディレクトリパス: {data_root}/persona/{name}

        名前はパスの1セグメントとして検証する。MagicMock のような非文字列や、
        区切り文字を含む名前がそのまま通ると、実データ領域にゴミのディレクトリが
        増える（実際に data/persona/<MagicMock ...>/ が76個できていた）。
        """
        if not isinstance(persona_name, str) or not _PERSONA_NAME_RE.match(persona_name):
            raise ValueError(f"不正なペルソナ名: {persona_name!r}")
        return f"{self.persona_dir}/{persona_name}"

    # ペルソナ配下のサブディレクトリ。sandbox から見えるのは media / wiki /
    # uploads / workspace だけで、db と config.json は見せない。
    def persona_db_dir(self, persona_name: str) -> str:
        """DB の置き場: {data_root}/persona/{name}/db"""
        return f"{self.persona_path(persona_name)}/db"

    def persona_media_dir(self, persona_name: str) -> str:
        """生成物の置き場（images / tts_cache / avatar）: .../media"""
        return f"{self.persona_path(persona_name)}/media"

    def persona_wiki_dir(self, persona_name: str) -> str:
        """wiki の置き場: .../wiki"""
        return f"{self.persona_path(persona_name)}/wiki"

    def persona_uploads_dir(self, persona_name: str) -> str:
        """ユーザーが上げたファイルの置き場: .../uploads"""
        return f"{self.persona_path(persona_name)}/uploads"

    @computed_field
    @property
    def import_dir(self) -> str:
        """Auto-Import ZIP配置ディレクトリ: {data_root}/import"""
        return f"{self.data_root}/import"

    @computed_field
    @property
    def cache_dir(self) -> str:
        """モデルキャッシュディレクトリ: {data_root}/cache"""
        return f"{self.data_root}/cache"

    @computed_field
    @property
    def config_dir(self) -> str:
        """設定ファイルディレクトリ: {data_root}/config"""
        return f"{self.data_root}/config"

    @computed_field
    @property
    def skills_dir(self) -> str:
        """Skillsファイルディレクトリ（data_root内）"""
        return f"{self.data_root}/skills"

    def ensure_directories(self) -> None:
        """起動時に必要なディレクトリを全て作成する。"""
        dirs = [
            self.persona_dir,
            self.import_dir,
            Path(self.import_dir) / "done",
            self.cache_dir,
            Path(self.cache_dir) / "huggingface",
            self.config_dir,
            self.skills_dir,
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        # 旧レイアウト（persona/<p>/memory.sqlite 等）からの移行。DB を開く前
        # にしか走らないので、冪等でも移動中の WAL を壊す心配はない。
        from nous.infrastructure.persona_layout import migrate_persona_layout

        migrate_persona_layout(Path(self.data_root))


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton (thread-safe via lru_cache)."""
    return Settings()
