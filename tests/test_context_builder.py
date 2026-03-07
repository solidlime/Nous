"""
agent.context_builder.ContextBuilder のユニットテスト。

外部 API・LLM への依存はなく、全て SQLite ベースなので
一時 DB を使って純粋にテストできる。
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, "D:/VSCode/Nous")

from agent.context_builder import ContextBuilder
from memory.db import MemoryDB
from memory.schema import MemoryEntry
from memory.conversation_db import ConversationDB
from psychology.emotional_model import EmotionalModel
from psychology.drive_system import DriveSystem
from psychology.goal_manager import GoalManager
from datetime import datetime


def _tmp_paths() -> dict:
    """テスト用の一時ファイルパスを返す。"""
    tmp = tempfile.mkdtemp()
    persona = "test_ctx"
    base = os.path.join(tmp, persona)
    return {
        "persona": persona,
        "memory_db": os.path.join(base, "memory.db"),
        "conv_db": os.path.join(base, "conversations.db"),
        "psych_db": os.path.join(base, "psychology.db"),
    }


def _make_builder(paths: dict, config: dict = None) -> ContextBuilder:
    cfg = config or {"conversation": {"max_silence_hours": 8.0}}
    p = paths["persona"]
    return ContextBuilder(
        persona=p,
        memory_db=MemoryDB(paths["memory_db"]),
        conv_db=ConversationDB(paths["conv_db"]),
        emotional_model=EmotionalModel(p, paths["psych_db"]),
        drive_system=DriveSystem(p, paths["psych_db"]),
        goal_manager=GoalManager(p, paths["psych_db"]),
        config=cfg,
    )


# ── build_web_context 正常系 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_web_context_returns_list():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    messages = await builder.build_web_context("こんにちは")
    assert isinstance(messages, list)
    assert len(messages) >= 2  # system + user


@pytest.mark.asyncio
async def test_build_web_context_first_message_is_system():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    messages = await builder.build_web_context("テスト")
    assert messages[0]["role"] == "system"


@pytest.mark.asyncio
async def test_build_web_context_last_message_is_user_input():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    user_input = "何を考えているの？"
    messages = await builder.build_web_context(user_input)
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == user_input


@pytest.mark.asyncio
async def test_build_web_context_system_prompt_contains_persona():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    messages = await builder.build_web_context("ping")
    system_content = messages[0]["content"]
    assert paths["persona"] in system_content


@pytest.mark.asyncio
async def test_build_web_context_with_custom_system_prompt():
    paths = _tmp_paths()
    custom_prompt = "カスタムシステムプロンプト"
    cfg = {
        "conversation": {"max_silence_hours": 8.0},
        "personas": {paths["persona"]: {"system_prompt": custom_prompt}},
    }
    builder = _make_builder(paths, config=cfg)
    messages = await builder.build_web_context("hello")
    assert messages[0]["content"] == custom_prompt


# ── build_consciousness_context 正常系 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_build_consciousness_context_returns_string():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    ctx = await builder.build_consciousness_context()
    assert isinstance(ctx, str)
    assert len(ctx) > 0


@pytest.mark.asyncio
async def test_build_consciousness_context_contains_persona_name():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    ctx = await builder.build_consciousness_context()
    assert paths["persona"] in ctx


@pytest.mark.asyncio
async def test_build_consciousness_context_contains_emotion_info():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    ctx = await builder.build_consciousness_context()
    assert "感情" in ctx or "neutral" in ctx


@pytest.mark.asyncio
async def test_build_consciousness_context_with_memories():
    paths = _tmp_paths()
    builder = _make_builder(paths)
    # 記憶を追加しておく
    now = datetime.now().isoformat()
    builder._memory_db.save(MemoryEntry(
        key="ctx_test_001",
        content="テスト記憶コンテンツ",
        created_at=now,
        updated_at=now,
    ))
    ctx = await builder.build_consciousness_context()
    assert isinstance(ctx, str)
    assert len(ctx) > 0


# ── build_event_context 正常系 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_event_context_contains_event_type():
    paths = _tmp_paths()
    builder = _make_builder(paths)

    from agent.event_bus import AgentEvent, EventType
    event = AgentEvent(
        priority=1,
        event_type=EventType.DISCORD_MESSAGE,
        persona=paths["persona"],
        data={"content": "hello from discord"},
    )
    ctx = await builder.build_event_context(event)
    assert "discord_message" in ctx.lower() or "DISCORD_MESSAGE" in ctx


@pytest.mark.asyncio
async def test_build_event_context_returns_string():
    paths = _tmp_paths()
    builder = _make_builder(paths)

    from agent.event_bus import AgentEvent, EventType
    event = AgentEvent(
        priority=1,
        event_type=EventType.DISCORD_MESSAGE,
        persona=paths["persona"],
        data={"content": "test"},
    )
    ctx = await builder.build_event_context(event)
    assert isinstance(ctx, str)
    assert len(ctx) > 0
