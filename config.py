"""
Nous プロジェクト設定管理モジュール。

MemoryMCP の config_utils.py を参考にクラスベース設計へ一新。
Config singleton パターンで設定を一元管理する。

優先順位（高い順）:
  環境変数 (NOUS_*) > config.json > DEFAULT_CONFIG
"""

import json
import os
import threading
from copy import deepcopy
from typing import Any, Dict, Iterable

# プロジェクトルートは config.py 自身のディレクトリ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG: Dict[str, Any] = {
    # ── サーバー設定 ──────────────────────────────────────────────────────────
    "server_host": "0.0.0.0",
    # 26263: MemoryMCP の 26262 と被らないよう
    "server_port": 26263,
    "timezone": "Asia/Tokyo",

    # ── ペルソナ設定 ──────────────────────────────────────────────────────────
    "default_persona": "nous",
    "active_personas": ["nous"],

    # ── リソースプロファイル ──────────────────────────────────────────────────
    # "normal" | "low" (NAS向け) | "minimal"
    "resource_profile": "low",

    # ── 埋め込みモデル ────────────────────────────────────────────────────────
    "embeddings_model": "cl-nagoya/ruri-v3-30m",
    "embeddings_device": "cpu",
    "reranker_model": "hotchpotch/japanese-reranker-xsmall-v2",
    "reranker_top_n": 10,
    "sentiment_model": "cardiffnlp/twitter-xlm-roberta-base-sentiment",

    # ── Qdrant 設定 ───────────────────────────────────────────────────────────
    "qdrant_url": "http://localhost:6333",
    "qdrant_api_key": None,
    # nous_ プレフィックスで MemoryMCP コレクションと名前が被らない
    "qdrant_collection_prefix": "nous_",

    # ── コンテキスト表示設定 ──────────────────────────────────────────────────
    "recent_memories_count": 5,
    "memory_preview_length": 100,

    # ── 会話スレッド設定 ──────────────────────────────────────────────────────
    "conversation": {
        # この時間以上沈黙したら新規スレッドを作成する
        "max_silence_hours": 8.0,
    },

    # ── LLM 設定 ──────────────────────────────────────────────────────────────
    # settings.html / main.py の両方が llm.ollama / llm.claude / llm.openrouter
    # のネスト形式で読み書きするため、DEFAULT_CONFIG もそれに合わせる。
    "llm": {
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "gemma3",
            "timeout_sec": 120,
        },
        "claude": {
            "api_key": None,
            "model": "claude-sonnet-4-6",
            "max_tokens": 1000,
        },
        "openrouter": {
            "api_key": None,
            "model": "google/gemma-3-9b-it",
            "site_url": "",
        },
        # タスク種別 → プロバイダー or {provider, model} のルーティングテーブル
        # 空 dict の場合は llm/router.py の DEFAULT_ROUTING_TABLE が使われる
        "routing": {},
    },

    # ── Discord 設定 ──────────────────────────────────────────────────────────
    "discord": {
        "enabled": False,
        "bot_token": None,  # main.py が discord_cfg.get("bot_token") で読む
        "guild_id": None,
        "channel_id": None,
        "prefix": "!",
        # メンション or DM でのみ応答
        "mention_only": True,
    },

    # ── 音声設定 ──────────────────────────────────────────────────────────────
    "voice": {
        "enabled": False,
        "provider": "voicevox",
        "voicevox_url": "http://localhost:50021",
        "speaker_id": 0,
        "speed_scale": 1.0,
        "pitch_scale": 0.0,
        # "elevenlabs"
        "elevenlabs_api_key": None,
        "elevenlabs_voice_id": None,
    },

    # ── アバター設定 ──────────────────────────────────────────────────────────
    # active_mode: "none" | "vrm" | "live2d"
    # vrm / live2d は排他選択（チャット UI で active_mode に従い描画）
    "avatar": {
        "active_mode": "vrm",
        "vtube_studio": {
            "enabled": False,
            "ws_url": "ws://localhost:8001",
            "plugin_name": "NousAgent",
        },
        "live2d_web": {
            "enabled": False,
            "model_path": "",
        },
        "vrm": {
            "enabled": True,
        },
    },

    # ── 意識ループ設定 ────────────────────────────────────────────────────────
    "consciousness": {
        "enabled": True,
        "interval_min_min": 30,
        "interval_max_min": 90,
        "nothing_cooldown_min": 15,
        "force_ticks": [],
    },

    # ── 心理モデル設定（グローバルデフォルト、ペルソナで上書き可） ─────────────
    "psychology": {
        "drive_thresholds": {
            "curiosity":   0.8,
            "boredom":     0.7,
            "connection":  0.75,
            "expression":  0.8,
            "mastery":     0.85,
        },
        "drive_tick_rate_per_hour": 0.05,
        # 旧形式との後方互換のため残す（emotion.emotional_inertia が優先される）
        "emotional_inertia": 0.7,
        # ── PAD感情 + OCC 評価パラメータ（新規） ─────────────────────────────
        # Big5 パーソナリティ特性 (0.0〜1.0)
        "personality": {
            "openness":          0.7,
            "conscientiousness": 0.6,
            "extraversion":      0.5,
            "agreeableness":     0.5,
            "neuroticism":       0.4,
        },
        # PAD感情モデル設定
        "emotion": {
            "emotional_inertia":  0.7,
            "pleasure_baseline":  0.0,
            "arousal_baseline":   0.0,
            "dominance_baseline": 0.0,
        },
        # OCC 評価エンジンの重み係数
        "appraisal": {
            "novelty_weight":  1.0,
            "social_weight":   1.0,
            "mastery_weight":  1.0,
        },
    },

    # ── 外部 MCP サーバー登録 ─────────────────────────────────────────────────
    # 各エントリ: {"name": str, "url": str, "enabled": bool, "auth_token": str | null}
    "mcp_servers": [],

    # ── 要約設定 ──────────────────────────────────────────────────────────────
    "summarization": {
        "enabled": True,
        "use_llm": False,
        "frequency_days": 1,
        "min_importance": 0.3,
        "idle_minutes": 30,
        "check_interval_seconds": 3600,
        "llm_api_url": None,
        "llm_api_key": None,
        "llm_model": "anthropic/claude-3.5-sonnet",
        "llm_max_tokens": 500,
        "llm_prompt": None,
    },

    # ── ベクトル再構築設定 ────────────────────────────────────────────────────
    "vector_rebuild": {
        "mode": "idle",
        "idle_seconds": 30,
        "min_interval": 120,
    },

    # ── 自動クリーンアップ設定 ────────────────────────────────────────────────
    "auto_cleanup": {
        "enabled": True,
        "idle_minutes": 30,
        "check_interval_seconds": 300,
        "duplicate_threshold": 0.90,
        "min_similarity_to_report": 0.85,
        "max_suggestions_per_run": 20,
    },

    # ── プログレッシブ検索設定 ────────────────────────────────────────────────
    "progressive_search": {
        "enabled": True,
        "keyword_first": True,
        "keyword_threshold": 3,
        "semantic_fallback": True,
        "max_semantic_top_k": 5,
    },

    # ── プライバシー設定 ──────────────────────────────────────────────────────
    "privacy": {
        "default_level": "internal",
        "auto_redact_pii": False,
        "search_max_level": "private",
        "dashboard_max_level": "internal",
    },

    # ── ダッシュボード設定 ────────────────────────────────────────────────────
    "dashboard": {
        "enabled": True,
        "timeline_days": 14,
    },

    # ── ペルソナ個別設定 ──────────────────────────────────────────────────────
    # 各ペルソナのカスタム設定。キーはペルソナ名。
    # 例: "personas": {"nous": {"system_prompt": "...", "tools_enabled": True}}
    "personas": {},

    # ── 昇華システム設定 ──────────────────────────────────────────────────────
    "elevation": {
        "enabled": True,
        "min_importance": 0.3,
        "check_interval_hours": 24,
        "max_per_run": 5,
    },

    # ── スケジューラ設定 ──────────────────────────────────────────────────────
    "scheduler": {
        "enabled": True,
        # 毎日の定時実行時刻 (0-23)
        "daily_hour": 3,
        # 週次実行曜日 (0=月曜)
        "weekly_day": 0,
    },
}

# ── リソースプロファイルプリセット ────────────────────────────────────────────
_RESOURCE_PROFILES: Dict[str, Dict[str, Any]] = {
    "low": {
        # NAS (DS920+ 20GB) 向け: CPU制約あり・メモリ余裕あり
        "embeddings_device": "cpu",
        "reranker_top_n": 6,
        "summarization": {
            "check_interval_seconds": 5400,
            "idle_minutes": 45,
        },
        "vector_rebuild": {
            "mode": "idle",
            "idle_seconds": 90,
            "min_interval": 300,
        },
        "auto_cleanup": {
            "check_interval_seconds": 450,
            "max_suggestions_per_run": 15,
        },
        "progressive_search": {
            "enabled": True,
            "keyword_first": True,
            "keyword_threshold": 2,
            "semantic_fallback": True,
            "max_semantic_top_k": 5,
        },
        "dashboard": {
            "timeline_days": 14,
        },
    },
    "minimal": {
        # 超低スペック環境 (Raspberry Pi 等)
        "embeddings_device": "cpu",
        "reranker_model": "",
        "reranker_top_n": 0,
        "summarization": {
            "enabled": False,
        },
        "vector_rebuild": {
            "mode": "manual",
            "min_interval": 3600,
        },
        "auto_cleanup": {
            "enabled": False,
        },
        "progressive_search": {
            "enabled": True,
            "keyword_first": True,
            "keyword_threshold": 1,
            "semantic_fallback": False,
            "max_semantic_top_k": 2,
        },
    },
}

# ── 内部キャッシュ ────────────────────────────────────────────────────────────
_ENV_PREFIX = "NOUS_"
_RESERVED_ENV_KEYS = {f"{_ENV_PREFIX}DATA_DIR"}

_config_cache: Dict[str, Any] = {}
_config_cache_lock = threading.Lock()
_config_cache_state: Dict[str, Any] = {
    "mtime": None,
    "env_signature": None,
}


def _deep_update(target: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """再帰的に target を updates で上書きする。"""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _deep_update_defaults_only(
    target: Dict[str, Any],
    updates: Dict[str, Any],
    defaults: Dict[str, Any],
) -> None:
    """target がまだデフォルト値のままの箇所だけ updates を適用する。"""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update_defaults_only(
                target[key],
                value,
                defaults.get(key, {}) if isinstance(defaults.get(key), dict) else {},
            )
        else:
            if target.get(key) == defaults.get(key):
                target[key] = value


def _assign_nested(target: Dict[str, Any], keys: Iterable[str], value: Any) -> None:
    """ネストされたキーパス (例: ["llm", "provider"]) に value をセットする。"""
    current = target
    *parents, leaf = list(keys)
    for key in parents:
        existing = current.get(key)
        if not isinstance(existing, dict):
            existing = {}
            current[key] = existing
        current = existing
    current[leaf] = value


def _parse_env_value(raw: str) -> Any:
    """環境変数文字列を適切な型にパースする。"""
    value = raw.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def _load_env_overrides() -> Dict[str, Any]:
    """NOUS_* 環境変数を設定 dict に変換する。"""
    overrides: Dict[str, Any] = {}
    for key, raw_value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        if key in _RESERVED_ENV_KEYS:
            continue
        suffix = key[len(_ENV_PREFIX):]
        if not suffix:
            continue
        lower = suffix.lower()
        value = _parse_env_value(raw_value)

        # ダブルアンダースコアでネスト (例: NOUS_LLM__PROVIDER)
        if "__" in suffix:
            parts = [seg for seg in lower.split("__") if seg]
            if parts:
                _assign_nested(overrides, parts, value)
            continue

        # 既知セクションのシングルアンダースコアマッピング
        known_sections = [
            "llm", "discord", "voice", "avatar",
            "consciousness", "psychology",
            "summarization", "vector_rebuild", "auto_cleanup",
            "progressive_search", "privacy", "dashboard",
            "elevation", "scheduler", "conversation", "personas",
        ]
        matched = False
        for section in known_sections:
            prefix_key = f"{section}_"
            if lower.startswith(prefix_key):
                leaf = lower[len(prefix_key):]
                _assign_nested(overrides, [section, leaf], value)
                matched = True
                break

        if not matched:
            _assign_nested(overrides, [lower], value)

    return overrides


def _apply_resource_profile(config: Dict[str, Any]) -> None:
    """リソースプロファイルプリセットを適用する。
    ユーザーが明示的に設定した値は上書きしない。
    """
    profile = config.get("resource_profile", "normal")
    if profile == "normal" or profile not in _RESOURCE_PROFILES:
        return
    preset = deepcopy(_RESOURCE_PROFILES[profile])
    _deep_update_defaults_only(config, preset, DEFAULT_CONFIG)


def get_data_dir() -> str:
    """データディレクトリのパスを返す。デフォルト: {BASE_DIR}/data/"""
    env_path = os.environ.get(f"{_ENV_PREFIX}DATA_DIR")
    if env_path:
        return os.path.abspath(env_path)
    return os.path.join(BASE_DIR, "data")


def get_config_path() -> str:
    """設定ファイルのパスを返す: {data_dir}/config.json"""
    return os.path.join(get_data_dir(), "config.json")


def _load_file_config(path: str) -> Dict[str, Any]:
    """config.json を読み込む。存在しない場合は空 dict を返す。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_config(force: bool = False) -> Dict[str, Any]:
    """設定を読み込み、キャッシュして返す。

    Args:
        force: True のとき強制的にファイルを再読み込みする (hot reload)。

    Returns:
        マージ済み設定 dict のコピー。
    """
    env_overrides = _load_env_overrides()
    env_signature = json.dumps(env_overrides, sort_keys=True, default=str)
    config_path = get_config_path()
    mtime = os.path.getmtime(config_path) if os.path.exists(config_path) else None

    with _config_cache_lock:
        cache_empty = not bool(_config_cache)
        cached_mtime = _config_cache_state.get("mtime")
        cached_env_sig = _config_cache_state.get("env_signature")

        if force or cache_empty or cached_mtime != mtime or cached_env_sig != env_signature:
            merged = deepcopy(DEFAULT_CONFIG)
            _deep_update(merged, env_overrides)
            file_config = _load_file_config(config_path)
            _deep_update(merged, file_config)

            # 環境変数の server_host / server_port はファイルより優先
            if "server_host" in env_overrides:
                merged["server_host"] = env_overrides["server_host"]
            if "server_port" in env_overrides:
                try:
                    merged["server_port"] = int(env_overrides["server_port"])
                except Exception:
                    merged["server_port"] = env_overrides["server_port"]

            _apply_resource_profile(merged)

            _config_cache.clear()
            _config_cache.update(merged)
            _config_cache_state["mtime"] = mtime
            _config_cache_state["env_signature"] = env_signature

    return deepcopy(_config_cache)


def get_config(key: str, default: Any = None) -> Any:
    """単一キーの設定値を取得する。"""
    return load_config().get(key, default)


# ── パス解決ヘルパー ──────────────────────────────────────────────────────────

def get_persona_dir(persona: str) -> str:
    """ペルソナ別データディレクトリ: data/{persona}/"""
    return os.path.join(get_data_dir(), persona)


def get_db_path(persona: str) -> str:
    """ペルソナ別 memory DB パス: data/{persona}/memory.db"""
    return os.path.join(get_persona_dir(persona), "memory.db")


def get_psychology_db_path(persona: str) -> str:
    """ペルソナ別 psychology DB パス: data/{persona}/psychology.db"""
    return os.path.join(get_persona_dir(persona), "psychology.db")


def get_conversation_db_path(persona: str) -> str:
    """ペルソナ別 conversation DB パス: data/{persona}/conversations.db"""
    return os.path.join(get_persona_dir(persona), "conversations.db")


def ensure_persona_dir(persona: str) -> str:
    """ペルソナ別データディレクトリを作成して返す。"""
    path = get_persona_dir(persona)
    os.makedirs(path, exist_ok=True)
    return path
