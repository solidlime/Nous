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
    # 発話単位の相関 ID（wiring イベントの連鎖境界）。service.chat が採番する。
    turn_id: str = ""
    # PrepareStep が埋める
    # (state_body, core_body)。タグ付けと並び順は injection.build_injection_block が持つ。
    context_section: tuple[str, str] = ("", "")
    time_context: str = ""  # 現在時刻の 1 行（[NOUS CONTEXT] の <current_state> 先頭行に入る）
    related_memories: str = ""
    state_raw: dict = field(default_factory=dict)
    memories_raw: list[dict] = field(default_factory=list)
    memories_objects: list = field(default_factory=list)
    # PrepareStep の Episode fallback が挿入した episode の構造化記録
    # （[{"key": "episode:<id>", "topic", "summary", "episode_id"}]）。
    # related_memories（文字列）と 1:1 で対応し、prompt_inject / SSE retrieved の
    # 「実際に挿入した集合」を memories_objects と合わせて与える。
    episodes_objects: list[dict] = field(default_factory=list)
    memory_debug: dict = field(default_factory=dict)
    # PromptBuildStep が埋める（静的領域 = キャッシュ対象・バイト不変）
    system_prompt: str = ""
    # PromptBuildStep が埋める（揮発領域 = [NOUS CONTEXT] として会話後方へ注入）
    volatile_context: str = ""
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
    # CompressStep が埋める（圧縮が起きたターンのみ）。service が ContextCompressedSSE を出す。
    _compression_info: dict | None = None
