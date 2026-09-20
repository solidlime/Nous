"""Tests for _tools_persona.py — get_context one-shot memory reading."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.api.mcp._tools_helpers import _MAX_PROJECT_CHARS
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success


def _make_memory(
    key: str = "mem_001",
    content: str = "test content",
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Memory:
    ts = created_at or datetime(2026, 7, 10, 12, 0)
    return Memory(
        key=key,
        content=content,
        tags=tags or [],
        created_at=ts,
        updated_at=updated_at or ts,
    )


@pytest.fixture
def mock_ctx():
    """Minimal mock AppContext for _tool_get_context."""
    ctx = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.memory_repo = MagicMock()
    ctx.persona_service = MagicMock()
    ctx.search_engine = MagicMock()
    ctx.equipment_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.entity_service = MagicMock()
    ctx.vector_store = None
    ctx.settings = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_get_context_skips_consumed_memories(mock_ctx):
    """consumed 済みメモリは空リストが返る → 注入されない"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])  # consumed = empty
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    # consumed はスキップされるので注入されない
    assert result["ok"] is True
    assert "前回セッションからの状態" not in result["result"]
    assert "口調" not in result["result"]


@pytest.mark.asyncio
async def test_get_context_includes_one_shot_memories(mock_ctx):
    """one-shot メモリが存在する場合は結果に含まれる"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.side_effect = [
        Success([_make_memory("m1", content="physical_state: 元気", tags=["physical_state"])]),
        Success([]),  # mental_state: consumed
        Success([]),  # audit M2 — due_reminder: no commitment due
    ]
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")
    assert result["ok"] is True
    assert "💪 身体状態" in result["result"]
    assert "元気" in result["result"]
    # mental_state consumed → not shown
    assert "🧠 精神状態" not in result["result"]


@pytest.mark.asyncio
async def test_get_context_both_one_shot_present(mock_ctx):
    """両方の one-shot メモリが存在する場合、両方とも表示される"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.side_effect = [
        Success([_make_memory("m1", content="physical_state: 元気", tags=["physical_state"])]),
        Success([_make_memory("m2", content="mental_state: 集中", tags=["mental_state"])]),
        Success([]),  # audit M2 — due_reminder: no commitment due
    ]
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")
    assert result["ok"] is True
    assert "💪 身体状態" in result["result"]
    assert "元気" in result["result"]
    assert "🧠 精神状態" in result["result"]
    assert "集中" in result["result"]


@pytest.mark.asyncio
async def test_get_context_dedup_recent_vs_top_memories(mock_ctx):
    """top_memories と recent で同一 key の記憶は recent 側から除外され、重複表示されない"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    shared = _make_memory("shared_key", content="SHARED_MEMORY_CONTENT", tags=["episodic"])
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([shared])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([shared])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    # ESSENTIAL STORY には出るが Recent Memories では除外され、本文に1回だけ現れる
    assert result["ok"] is True
    assert "SHARED_MEMORY_CONTENT" in result["result"]
    assert result["result"].count("SHARED_MEMORY_CONTENT") == 1


@pytest.mark.asyncio
async def test_get_context_summaries_sorted_by_updated_at(mock_ctx):
    """session_summary は updated_at 降順でソートされ、最新のサマリが先に表示される"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    # 古い updated_at だが新しい created_at を持つ記憶（ソートが created_at でないことを検証）
    old = _make_memory(
        "sum_old",
        content="OLD_SUMMARY_TEXT",
        tags=["session_summary"],
        created_at=datetime(2026, 8, 10),
        updated_at=datetime(2026, 7, 1),
    )
    new = _make_memory(
        "sum_new",
        content="NEW_SUMMARY_TEXT",
        tags=["session_summary"],
        created_at=datetime(2026, 7, 1),
        updated_at=datetime(2026, 8, 10),
    )
    mock_ctx.persona_service.get_context.return_value = Success(state)

    def get_by_tags_side_effect(tags, include_consumed=False):
        if tags == ["session_summary"]:
            return Success([old, new])  # 並び順は保証されない想定（古い順で返す）
        return Success([])

    mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert "📝 NEW_SUMMARY_TEXT" in result["result"]
    assert "📝 OLD_SUMMARY_TEXT" in result["result"]
    # updated_at が新しい NEW が先に表示される
    assert result["result"].index("NEW_SUMMARY_TEXT") < result["result"].index("OLD_SUMMARY_TEXT")


# ---------------------------------------------------------------------------
# get_context: project オプション付き記憶（PROJECT MEMORIES 節）
# ---------------------------------------------------------------------------


def _project_memories(keys_and_ts: list[tuple[str, datetime, str]]) -> list:
    """(key, updated_at, content) の組から Memory を作る。"""
    mems = []
    for i, (key, ts, content) in enumerate(keys_and_ts):
        created = datetime(2026, 7, 1) if i == 0 else ts
        mems.append(
            _make_memory(key=key, content=content, tags=["project:testslug"], created_at=created, updated_at=ts)
        )
    return mems


@pytest.mark.asyncio
async def test_get_context_with_project_memories(mock_ctx):
    """project 指定時: project:<slug> タグ付き記憶が updated_at 降順・最大5件・
    _MAX_PROJECT_CHARS 字キャップで PROJECT MEMORIES 節に表示される。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    base = datetime(2026, 8, 1, 0, 0)
    # get_by_tags は並び順が保証されない想定（シャッフルして返す）
    mems = _project_memories(
        [
            ("proj_1", base + timedelta(minutes=1), "PROJECT_MEM_1"),
            ("proj_2", base + timedelta(minutes=2), "PROJECT_MEM_2"),
            ("proj_7", base + timedelta(minutes=7), "メモ" * 300),  # 長文 → 400字キャップの検証
            ("proj_3", base + timedelta(minutes=3), "PROJECT_MEM_3"),
            ("proj_6", base + timedelta(minutes=6), "PROJECT_MEM_6"),
            ("proj_4", base + timedelta(minutes=4), "PROJECT_MEM_4"),
            ("proj_5", base + timedelta(minutes=5), "PROJECT_MEM_5"),
        ]
    )

    def get_by_tags_side_effect(tags, include_consumed=False):
        if tags == ["project:testslug"]:
            return Success(mems)
        return Success([])

    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona", project="testslug")

    assert result["ok"] is True
    # 節見出し
    assert "--- PROJECT MEMORIES (project:testslug) ---" in result["result"]
    # updated_at 降順 → proj_7(最新・長文) が先頭、上位5件: proj_7, proj_6, proj_5, proj_4, proj_3
    r = result["result"]
    assert r.index("PROJECT_MEM_6") < r.index("PROJECT_MEM_5") < r.index("PROJECT_MEM_4") < r.index("PROJECT_MEM_3")
    # 古い2件（proj_1, proj_2）は落ちる
    assert "PROJECT_MEM_1" not in r
    assert "PROJECT_MEM_2" not in r
    # 文字数キャップ（_MAX_PROJECT_CHARS）: 長文は "… (full via memory_read: <key>)" 付きで切り詰め
    assert "(full via memory_read: proj_7)" in r
    assert "… (full via memory_read:" in r
    assert "メモ" * 300 not in r  # 全文は表示されない
    # 実効キャップ: _MAX_PROJECT_CHARS 字で切り詰められ、それ以降の文字は表示されない
    assert r.count("メモ") <= _MAX_PROJECT_CHARS // len("メモ")
    # get_by_tags は project:testslug タグで呼ばれる
    assert (["project:testslug"],) in [c.args for c in mock_ctx.memory_service.get_by_tags.call_args_list]


@pytest.mark.asyncio
async def test_get_context_project_no_tag_matches(mock_ctx):
    """project タグ無し → PROJECT MEMORIES 節（見出し）自体が出ない。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona", project="testslug")

    assert result["ok"] is True
    assert "PROJECT MEMORIES" not in result["result"]


@pytest.mark.asyncio
async def test_get_context_without_project_backward_compat(mock_ctx):
    """project 引数なし → 従来通り動作し PROJECT MEMORIES 節が出ない（後方互換）。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert "CURRENT STATE" in result["result"]
    assert "PROJECT MEMORIES" not in result["result"]


# ---------------------------------------------------------------------------
# get_context: 重複除去（dedupe / near-duplicate collapse）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_context_essential_story_dedupes_normalized_content(mock_ctx):
    """Essential Story に同内容の別キー記憶が2件 → 1件だけ表示される。
    NFKC（全角数字/全角空白）・空白列・タイムスタンプの差は正規化後同一扱いになる。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    m1 = _make_memory("es_1", content="2025-01-01 10:30 再起動した。")  # 先頭の日時
    m2 = _make_memory("es_2", content="２０２５-０１-０１ 再起動した。")  # 全角数字のみ・先頭
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([m1, m2])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert result["result"].count("再起動した。") == 1


# near-dup fixture（実データから採取した chezmoi 記録。テスト5）
_CHEZMOI_FIXTURES = [
    "type省略時のデフォルト挙動が配布経路まで変えるのか、最小リポジトリで実際に確かめるところまではまだ届いていないな。",
    "調べたら、シェル実行やファイル書き込み、ディレクトリ作成、環境確認の手段が一通り見つかった。これなら最小構成リポジトリで type を変えながら ~/.agents/skills への配布経路を確認できる。",
    "chezmoi externals の type 省略時の影響を、最小構成リポジトリで type を変えながら配布経路を確認する。次に時間ができたら必ず試す。",
    "chezmoi externalsでtypeを省略したときの~/.agents/skillsへの配布経路の変化を、最小リポジトリで実際に確かめられなかった。",
    "chezmoi externalsのtype省略時の影響は、最小構成リポジトリでtypeを変えながら配布経路を確認するのが確実。次に時間ができたら実際に試して片付ける。",
]
# 実測 ratio（difflib.SequenceMatcher、正規化なし・正規化後も同値）:
#   3-5 = 0.8589（唯一 0.85 以上のペア → collapse で 5 が落ちる）
#   3-4 = 0.4586 / 1-4 = 0.4234 / 4-5 = 0.4074 / 2-3 = 0.3626 / 2-4 = 0.3425
#   / 2-5 = 0.3422 / 1-5 = 0.3077 / 1-3 = 0.2899 / 1-2 = 0.1728
# 近傍重複の根本対策は書き込み側 duplicate check（memory_create の skip_duplicate_check 運用）
# であり、表示側 threshold は保守的に 0.85 を維持（実測: 3-5=0.8589、次点 2-3=0.3626）。


@pytest.mark.asyncio
async def test_get_context_recent_near_duplicates_collapse(mock_ctx):
    """近傍重複 fixture 5件 → recent 節で 4件（3-5 ペアのみ 0.85 超で 5 が落ちる）。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    recent_mems = [_make_memory(f"chez_{i}", content=c) for i, c in enumerate(_CHEZMOI_FIXTURES, start=1)]
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success(recent_mems)
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    r = result["result"]
    assert result["ok"] is True
    recent_section = r.split("--- Your Recent Memories ---")[1].split("Use memory_search()")[0]
    bullets = [ln for ln in recent_section.splitlines() if ln.startswith("- ")]
    assert len(bullets) <= 4
    # 残るのは 1..4、5 は 3 との近傍ペア（0.8589 >= 0.85）で落ちる
    assert "配布経路まで変えるのか" in r  # 1
    assert "シェル実行やファイル書き込み" in r  # 2
    assert "次に時間ができたら必ず試す" in r  # 3
    assert "実際に確かめられなかった" in r  # 4
    assert "確認するのが確実" not in r  # 5 は collapse される


@pytest.mark.asyncio
async def test_get_context_distinct_memories_not_collapsed(mock_ctx):
    """内容が明確に異なる2件（ratio 0.2727 < _NEAR_DUP_THRESHOLD）は圧縮されない。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    # difflib.SequenceMatcher 実測: 0.2727（0.85 を大きく下回る）
    recent_mems = [
        _make_memory("dist_1", content="朝にジョギングをした。"),
        _make_memory("dist_2", content="図書館で小説を借りた。"),
    ]
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success(recent_mems)
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert "朝にジョギングをした。" in result["result"]
    assert "図書館で小説を借りた。" in result["result"]


@pytest.mark.asyncio
async def test_get_context_cross_section_dedupe(mock_ctx):
    """節跨ぎ dedupe: 同一内容が recent と essential story の両方にある → 先に構築される
    recent 側だけに出る（essential story 側は seen set で排除）。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    shared_content = "重複する内容です"
    m_recent = _make_memory("rec_key", content=shared_content)
    m_top = _make_memory("top_key", content=shared_content)
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([m_top])
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([m_recent])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    r = result["result"]
    assert result["ok"] is True
    assert r.count(shared_content) == 1
    # recent 節の中にある（essential story の前に）
    recent_section = r.split("--- Your Recent Memories ---")[1].split("## YOUR ESSENTIAL STORY")[0]
    assert shared_content in recent_section


@pytest.mark.asyncio
async def test_get_context_inline_datetime_not_deduplicated(mock_ctx):
    """本文中の日時・スコア表記は正当な差異として保持される（先頭以外の日時は除去で消さない）。
    実測 ratio: 0.7500 < _NEAR_DUP_THRESHOLD なので両方表示される。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    top_mems = [
        _make_memory("dt_1", content="本日の試合はスコア 3:2 で終わった。"),
        _make_memory("dt_2", content="昨日の試合はスコア 1:0 で始まった。"),
    ]
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success(top_mems)
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success([])
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    assert result["ok"] is True
    assert result["result"].count("試合はスコア") == 2
    assert "3:2" in result["result"]
    assert "1:0" in result["result"]


@pytest.mark.asyncio
async def test_get_context_empty_section_header_suppressed(mock_ctx):
    """節の全項目が節間 dedupe で消えた場合、空の見出し（--- Your Recent Memories ---）を出さない。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    goal_mem = _make_memory("goal_1", content="共通の覚書", tags=["goal", "active"])
    recent_mems = [
        _make_memory("rec_1", content="共通の覚書"),
        _make_memory("rec_2", content="共通の覚書"),
    ]

    def get_by_tags_side_effect(tags, include_consumed=False):
        if tags == ["goal"]:
            return Success([goal_mem])
        return Success([])

    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_by_tags.side_effect = get_by_tags_side_effect
    mock_ctx.memory_service.get_top_by_importance.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success(recent_mems)
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    r = result["result"]
    assert result["ok"] is True
    # ACTIVE COMMITMENTS 節（先に構築）のみに出る
    assert "⚠️ YOUR ACTIVE COMMITMENTS:" in r
    assert r.count("共通の覚書") == 1
    # recent 節は全件 dedupe され空 → 見出しを出さない
    assert "--- Your Recent Memories ---" not in r


@pytest.mark.asyncio
async def test_get_context_collapsed_norm_blocks_later_section(mock_ctx):
    """collapse で落とした項目の正規化済み内容が seen に登録され、
    後続節（essential story）の同内容の完全一致項目も表示されない。"""
    from nous.api.mcp._tools_persona import _tool_get_context
    from nous.domain.persona.entities import PersonaState

    state = PersonaState(persona="test_persona")
    # chez3 と chez5 は近傍ペア（実測 ratio 0.8589 >= 0.85）→ recent で chez5 が落ちる
    chez3 = _CHEZMOI_FIXTURES[2]
    chez5 = _CHEZMOI_FIXTURES[4]
    recent_mems = [_make_memory("chez_3", content=chez3), _make_memory("chez_5", content=chez5)]
    # essential story 側に chez5 と同一内容の別キー記憶がある（素通りすると表示されてしまう）
    top_mems = [_make_memory("top_c", content=chez5)]
    mock_ctx.persona_service.get_context.return_value = Success(state)
    mock_ctx.memory_service.get_top_by_importance.return_value = Success(top_mems)
    mock_ctx.memory_service.get_by_tags.return_value = Success([])
    mock_ctx.memory_service.get_and_consume_one_shot.return_value = Success([])
    mock_ctx.persona_service.get_emotion_history.return_value = Success([])
    mock_ctx.persona_service.get_body_state_history.return_value = Success([])
    mock_ctx.memory_service.get_recent.return_value = Success(recent_mems)
    mock_ctx.equipment_service.get_equipment.return_value = Success({})
    mock_ctx.persona_service.record_conversation_time.return_value = Success(None)

    result = await _tool_get_context(mock_ctx, "test_persona")

    r = result["result"]
    assert result["ok"] is True
    # chez3 は recent 節に表示される
    assert "次に時間ができたら必ず試す" in r
    # chez5 は recent で collapse され、essential story の同内容も seen により表示されない
    assert "確認するのが確実" not in r
    assert "## YOUR ESSENTIAL STORY" not in r
