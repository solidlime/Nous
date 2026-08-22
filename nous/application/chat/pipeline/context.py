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
    time_context: str = ""  # ★ <TIME_CONTEXT> ブロック（システムプロンプト先頭に注入）
    related_memories: str = ""
    recency_digest: str = ""  # PrepareStep が埋める（§1 直近記憶ダイジェスト）
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
    # InferenceStep が埋める (インタラクティブに追記)
    was_truncated: bool = False  # max_tokens到達による応答切断が発生したか
    # LLM プロバイダーから返された usage 情報
    usage: dict | None = None
    # セグメント順序記録（F2 履歴復元用: text/tool_call/tool_result の順序を保持）
    segments: list[dict] = field(default_factory=list)
    # TreeSessionWindow.add() が生成した msg_id
    user_msg_id: str = ""
    assistant_msg_id: str = ""
