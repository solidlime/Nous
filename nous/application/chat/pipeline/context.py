"""ChatTurnContext: 1チャットターンの状態コンテナ。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMMessage


@dataclass
class ChatTurnContext:
    session_id: str
    user_message: str
    images: list[dict] = field(default_factory=list)
    # PrepareStep が埋める
    context_section: str = ""
    related_memories: str = ""
    state_raw: dict = field(default_factory=dict)
    memories_raw: list[dict] = field(default_factory=list)
    memories_objects: list = field(default_factory=list)
    memory_debug: dict = field(default_factory=dict)
    # Author's Note (injected into system prompt)
    author_note: str | None = None
    author_note_frequency: str = "always"
    # PromptBuildStep が埋める
    system_prompt: str = ""
    skills_raw: list[dict] = field(default_factory=list)
    # InferenceStep が埋める (インタラクティブに追記)
    messages: list[LLMMessage] = field(default_factory=list)
    full_response: str = ""
    tool_calls_log: list[dict] = field(default_factory=list)
    tool_call_count: int = 0
