"""SSEイベント型定義 — チャットストリーミング用 dataclass群。"""

from __future__ import annotations

import json
from dataclasses import dataclass


def _sse_encode(event_type: str, data: dict) -> str:
    def _default(obj):
        try:
            return str(obj)
        except Exception:
            return "<not serializable>"

    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False, default=_default)
    return f"data: {payload}\n\n"


@dataclass
class TextDeltaSSE:
    content: str

    def to_sse(self) -> str:
        return _sse_encode("text_delta", {"content": self.content})


@dataclass
class ThinkingDeltaSSE:
    content: str

    def to_sse(self) -> str:
        return _sse_encode("thinking_delta", {"content": self.content})


@dataclass
class ToolCallSSE:
    name: str
    input: dict
    id: str

    def to_sse(self) -> str:
        return _sse_encode("tool_call", {"name": self.name, "input": self.input, "id": self.id})


@dataclass
class ToolResultSSE:
    name: str
    result: object
    id: str

    def to_sse(self) -> str:
        return _sse_encode("tool_result", {"name": self.name, "result": self.result, "id": self.id})


@dataclass
class DebugInfoSSE:
    data: dict

    def to_sse(self) -> str:
        return _sse_encode("debug_info", self.data)


@dataclass
class DoneSSE:
    message: str = "completed"
    truncated: bool = False
    usage: dict | None = None
    user_msg_id: str = ""
    assistant_msg_id: str = ""

    def to_sse(self) -> str:
        data: dict = {"message": self.message, "truncated": self.truncated}
        if self.usage:
            data["usage"] = self.usage
        if self.user_msg_id:
            data["user_msg_id"] = self.user_msg_id
        if self.assistant_msg_id:
            data["assistant_msg_id"] = self.assistant_msg_id
        return _sse_encode("done", data)


@dataclass
class ErrorSSE:
    message: str

    def to_sse(self) -> str:
        return _sse_encode("error", {"message": self.message})


@dataclass
class MemoryActivitySSE:
    """Memory retrieval and save activity for this turn."""

    retrieved: list  # list of {"content": str, "score": float, "importance": float}
    saved: list  # list of {"content": str, "tags": list}
    goals: list | None = None  # list of {"content": str} newly saved goals
    promises: list | None = None  # list of {"content": str} newly saved promises

    def to_sse(self) -> str:
        return _sse_encode(
            "memory_activity",
            {
                "retrieved": self.retrieved,
                "saved": self.saved,
                "goals": self.goals or [],
                "promises": self.promises or [],
            },
        )


@dataclass
class ReflectionStartSSE:
    def to_sse(self) -> str:
        return _sse_encode("reflection_start", {})


@dataclass
class ReflectionDoneSSE:
    insights: list  # list of insight strings

    def to_sse(self) -> str:
        return _sse_encode("reflection_done", {"insights": self.insights})


@dataclass
class MentalModelStartSSE:
    message: str = ""

    def to_sse(self) -> str:
        return _sse_encode("mental_model_start", {"message": self.message})


@dataclass
class MentalModelDoneSSE:
    message: str = ""

    def to_sse(self) -> str:
        return _sse_encode("mental_model_done", {"message": self.message})


@dataclass
class SessionSummarizedSSE:
    summary: str

    def to_sse(self) -> str:
        return _sse_encode("session_summarized", {"summary": self.summary})


@dataclass
class ContextUpdateSSE:
    """Persona state changes detected during turn processing."""

    update: dict  # {"emotion": "...", "mental_state": "...", "physical_state": "...", etc}

    def to_sse(self) -> str:
        return _sse_encode("context_update", {"update": self.update})


@dataclass
class InventoryUpdateSSE:
    """Equipment/inventory changes detected during turn processing."""

    update: dict  # {"equip": {...}, "unequip": [...], "add_items": [...], ...}

    def to_sse(self) -> str:
        return _sse_encode("inventory_update", {"update": self.update})


@dataclass
class CharacterFlagSSE:
    """キャラ一貫性判定の違反フラグ（非破壊・表示のみ）"""

    violation: str  # "tone" | "compliance" | "character"
    detail: str

    def to_sse(self) -> str:
        return _sse_encode("character_flag", {"violation": self.violation, "detail": self.detail})


@dataclass
class ContextCompressedSSE:
    """Notification when context compression occurs."""

    before_tokens: int
    after_tokens: int
    budget: int
    mode: str  # "light"|"normal"|"aggressive" — which compression stage applied

    def to_sse(self) -> str:
        return _sse_encode(
            "context_compressed",
            {
                "before_tokens": self.before_tokens,
                "after_tokens": self.after_tokens,
                "budget": self.budget,
                "mode": self.mode,
            },
        )


@dataclass
class ImageGenStartSSE:
    """画像生成開始イベント"""

    provider: str  # "comfyui"
    prompt: str  # 生成プロンプト（先頭100文字）
    n: int  # 生成枚数
    type: str = "image_gen_start"

    def to_sse(self) -> str:
        return _sse_encode(
            "image_gen_start",
            {"provider": self.provider, "prompt": self.prompt, "n": self.n},
        )


@dataclass
class ImageGenResultSSE:
    """画像生成結果イベント"""

    images: list  # [{base64: str, revised_prompt: str, size: str}]
    provider: str  # "comfyui"
    tool_use_id: str = ""  # 対応する tool_call の ID（並列ツール時の順序正規化用）
    self_portrait: bool = False  # self-portrait 生成時は True（Overview 自動更新用）
    type: str = "image_gen_result"

    def to_sse(self) -> str:
        return _sse_encode(
            "image_gen_result",
            {
                "images": self.images,
                "provider": self.provider,
                "tool_use_id": self.tool_use_id,
                "self_portrait": self.self_portrait,
            },
        )


@dataclass
class SkillLoadSSE:
    """スキル読み込み完了イベント（セッション初回のみ発火）"""

    skill_names: list[str]
    type: str = "skill_load"

    def to_sse(self) -> str:
        return _sse_encode("skill_load", {"skill_names": self.skill_names})
