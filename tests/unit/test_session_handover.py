"""プロジェクト引き継ぎ栞（kanban #58）— 決定論なので LLM もネットワークも要らない。"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.api.mcp import _tools_persona
from nous.application.handover import AUTO_TAG, build_handover, handover_key
from nous.domain.memory.entities import Memory
from nous.domain.memory.service import MemoryService
from nous.domain.persona.entities import PersonaState
from nous.domain.shared.result import Success
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

JST = timezone(timedelta(hours=9))
PERSONA = "herta"
PROJECT = "nous"
NOW = datetime(2026, 11, 15, 3, 30, tzinfo=JST)


def _mem(key: str, content: str, *, minutes_ago: int = 0, tags: list[str] | None = None) -> Memory:
    at = NOW - timedelta(minutes=minutes_ago)
    return Memory(
        key=key,
        content=content,
        created_at=at,
        updated_at=at,
        tags=tags if tags is not None else [f"project:{PROJECT}"],
        kind="semantic",
        source_type="user_stated",
    )


# ----------------------------------------------------------------------
# 純関数
# ----------------------------------------------------------------------


def test_empty_input_returns_empty_string():
    assert build_handover(PROJECT, [], [], NOW) == ""


def test_one_line_with_done_topics_and_next_step():
    memories = [
        _mem("m1", "session_begin に栞を注入した", minutes_ago=10),
        _mem("m2", "handover の単体テストを書いた", minutes_ago=20),
        _mem("m3", "ruff を通した", minutes_ago=30),
        _mem("m4", "古すぎる作業", minutes_ago=300),
    ]
    questions = ["並行編集の衝突は？", "limit は 400 で足りる？", "wiki 側は誰が触る？"]

    text = build_handover(PROJECT, memories, questions, NOW)

    assert "\n" not in text
    assert text.startswith("完了: session_begin に栞を注入した")
    assert "/ handover の単体テストを書いた" in text
    assert "古すぎる作業" not in text  # 直近3件まで
    assert "論点: 並行編集の衝突は？ / limit は 400 で足りる？" in text
    assert "次: wiki 側は誰が触る？" in text  # 最古の未解決
    # LLM 呼び出しゼロ = 同じ入力なら同じ出力
    assert text == build_handover(PROJECT, memories, questions, NOW)


def test_limit_is_never_exceeded():
    memories = [_mem(f"m{i}", "長い作業ログ" * 40, minutes_ago=i) for i in range(3)]
    questions = ["長い論点" * 30, "もう一つの論点" * 30]

    for limit in (40, 120, 400):
        text = build_handover(PROJECT, memories, questions, NOW, limit=limit)
        assert len(text) <= limit
        assert text.endswith("…")


def test_explicit_handover_memory_wins():
    explicit = _mem(handover_key(PROJECT), "エージェントが自分で書いた引き継ぎ", minutes_ago=0)
    memories = [explicit, _mem("m1", "自動生成に使われる作業ログ", minutes_ago=5)]

    assert build_handover(PROJECT, memories, ["論点"], NOW) == "エージェントが自分で書いた引き継ぎ"


def test_auto_generated_handover_is_regenerated():
    """自動生成した栞（handover-auto タグ）には固定しない。"""
    auto = _mem(handover_key(PROJECT), "完了: 古い自動生成", minutes_ago=0, tags=["handover", AUTO_TAG])
    memories = [auto, _mem("m1", "新しい作業ログ", minutes_ago=5)]

    text = build_handover(PROJECT, memories, [], NOW)

    assert text == "完了: 新しい作業ログ"


def test_explicit_handover_is_also_cut_to_limit():
    explicit = _mem(handover_key(PROJECT), "長い" * 100, minutes_ago=0)

    text = build_handover(PROJECT, [explicit], [], NOW, limit=50)

    assert len(text) == 50
    assert text.endswith("…")


def test_open_question_never_shows_up_as_done():
    """未解決の問いが同じ記憶集合に入っていても「完了」側に混ぜない。"""
    q = _mem("q1", "400 字上限は足りる？", minutes_ago=1, tags=["open-question", f"project:{PROJECT}"])
    memories = [q, _mem("m1", "栞を注入した", minutes_ago=10)]

    text = build_handover(PROJECT, memories, [q.content], NOW)

    assert text.startswith("完了: 栞を注入した |")
    assert text.count("400 字上限は足りる？") == 2  # 論点 + 次 のみ


def test_questions_only_still_produces_a_line():
    text = build_handover(PROJECT, [], ["未解決だけある"], NOW)

    assert text == "論点: 未解決だけある | 次: 未解決だけある"


# ----------------------------------------------------------------------
# _tool_get_context / session_begin への注入
# ----------------------------------------------------------------------


def _ctx(tmp_path) -> MagicMock:
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.session_id = "s1"
    ctx.connection = conn
    ctx._config = None
    ctx.settings = MagicMock(data_root=str(tmp_path))
    ctx.event_bus.publish = AsyncMock()
    ctx.persona_service.get_context.return_value = Success(PersonaState(persona=PERSONA))
    ctx.persona_service.get_emotion_history.return_value = Success([])
    ctx.equipment_service.get_equipment.return_value = Success({})
    ctx.memory_service = MemoryService(repo)
    return ctx


async def _begin(ctx, project: str | None, session_effects: bool = True) -> str:
    payload = await _tools_persona._tool_session_begin(ctx, PERSONA, project=project)
    assert payload["ok"] is True
    result = payload["result"]
    assert isinstance(result, str)
    return result


@pytest.mark.asyncio
async def test_session_begin_injects_handover_line(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.memory_service.save_memory(_mem("m1", "セッション跨ぎの栞を実装中", minutes_ago=5))
    ctx.memory_service.save_memory(_mem("q1", "limit 400 で足りる？", minutes_ago=1, tags=["open-question"]))

    text = await _begin(ctx, PROJECT)

    assert "🔖 前回の引き継ぎ (project:nous): 完了: セッション跨ぎの栞を実装中" in text
    assert "次: limit 400 で足りる？" in text


@pytest.mark.asyncio
async def test_handover_line_is_kept_out_of_project_memories(tmp_path):
    """栞の記憶そのものを PROJECT MEMORIES 節に二重表示しない。"""
    ctx = _ctx(tmp_path)
    ctx.memory_service.save_memory(_mem("m1", "作業ログ", minutes_ago=5))

    text = await _begin(ctx, PROJECT)

    assert text.count("🔖 前回の引き継ぎ") == 1


@pytest.mark.asyncio
async def test_no_project_means_no_handover_line(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.memory_service.save_memory(_mem("m1", "作業ログ", minutes_ago=5))

    text = await _begin(ctx, None)

    assert "🔖 前回の引き継ぎ" not in text


@pytest.mark.asyncio
async def test_session_effects_upsert_the_handover_memory(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.memory_service.save_memory(_mem("m1", "一回目の作業", minutes_ago=5))

    await _begin(ctx, PROJECT)
    first = ctx.memory_service.get_memory(handover_key(PROJECT))
    assert isinstance(first, Success)
    assert first.value is not None
    assert "一回目の作業" in first.value.content
    created_at = first.value.created_at

    ctx.memory_service.save_memory(_mem("m2", "二回目の作業", minutes_ago=1))
    text = await _begin(ctx, PROJECT)

    second = ctx.memory_service.get_memory(handover_key(PROJECT))
    assert isinstance(second, Success)
    assert second.value is not None
    assert second.value.key == first.value.key  # 同じ key を上書き（増殖しない）
    assert second.value.created_at == created_at
    assert "二回目の作業" in second.value.content
    # 自動生成側は毎回作り直す（handover-auto タグ付き）ので、次回以降も内容が進む
    assert second.value.tags == ["handover", AUTO_TAG]
    assert "二回目の作業" in text


@pytest.mark.asyncio
async def test_explicit_handover_survives_session_effects(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.memory_service.save_memory(_mem(handover_key(PROJECT), "エージェントの手書き引き継ぎ", minutes_ago=0))
    ctx.memory_service.save_memory(_mem("m1", "自動生成の材料", minutes_ago=5))

    text = await _begin(ctx, PROJECT)
    text2 = await _begin(ctx, PROJECT)

    assert "エージェントの手書き引き継ぎ" in text
    assert "自動生成の材料" not in text.split("🔖")[1].splitlines()[0]
    assert "エージェントの手書き引き継ぎ" in text2


def test_session_begin_delegates_to_get_context_with_effects():
    """明示更新の上書き・upsert は session_effects 経路に乗っていること。"""
    source = inspect.getsource(_tools_persona._tool_get_context)
    assert "build_handover" in source
    assert "session_effects" in source
