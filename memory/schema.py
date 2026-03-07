"""
Nous memory エントリのデータクラス定義。

elevation フィールド (elevated / elevation_at / elevation_narrative /
elevation_emotion / elevation_significance) は MemoryMCP には存在しない
Nous 独自の拡張で、記憶を「昇華」して物語的意味を付与する機能に使用する。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryEntry:
    # ── 識別子 ───────────────────────────────────────────────────────────────
    key: str
    content: str

    # ── タイムスタンプ (ISO8601 文字列) ───────────────────────────────────────
    created_at: str
    updated_at: str

    # ── タグ・重要度 ──────────────────────────────────────────────────────────
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5

    # ── 感情状態 ──────────────────────────────────────────────────────────────
    emotion: str = "neutral"
    emotion_intensity: float = 0.0

    # ── 身体・精神・環境状態 ──────────────────────────────────────────────────
    physical_state: str = "normal"
    mental_state: str = "calm"
    environment: str = "unknown"
    relationship_status: str = "normal"

    # ── アクション・関連情報 ──────────────────────────────────────────────────
    action_tag: Optional[str] = None
    related_keys: List[str] = field(default_factory=list)
    summary_ref: Optional[str] = None

    # ── 装備アイテム {slot: item_name} ───────────────────────────────────────
    equipped_items: Optional[Dict[str, str]] = None

    # ── アクセス追跡 ──────────────────────────────────────────────────────────
    access_count: int = 0
    last_accessed: Optional[str] = None

    # ── プライバシー ──────────────────────────────────────────────────────────
    privacy_level: str = "internal"

    # ── 昇華フィールド (Nous 独自) ────────────────────────────────────────────
    # elevated: この記憶が昇華処理済みか
    elevated: bool = False
    # elevation_at: 昇華処理を行った日時 (ISO8601)
    elevation_at: Optional[str] = None
    # elevation_narrative: LLM が生成した物語的意味付けテキスト
    elevation_narrative: Optional[str] = None
    # elevation_emotion: 昇華時に付与した感情ラベル
    elevation_emotion: Optional[str] = None
    # elevation_significance: 昇華評価スコア (0.0–1.0)
    elevation_significance: Optional[float] = None
