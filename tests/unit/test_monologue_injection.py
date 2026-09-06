"""再会時 monologue 注入のテスト (spec §4.3)。

- 取得条件: enabled + repo + last_conversation_time + 経過 > 900s + ギャップ中エントリ
- 描画: <monologue_context> 兄弟タグ・動的領域 (__STATIC_END__ 以降)・生の < なし
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.context_loader import _fetch_monologue_entries
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.domain.memory.session_event import SessionEvent


def _event(ts: datetime, summary: str) -> SessionEvent:
    return SessionEvent(
        session_id="s",
        persona="herta",
        event_type="brain.monologue",
        summary=summary,
        timestamp=ts,
    )


def _fake_repo(events: list[SessionEvent]) -> MagicMock:
    repo = MagicMock()
    repo.get_by_persona.return_value = events
    return repo


def _ctx(repo) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx._session_event_repo = repo
    return ctx


def _state(lct: datetime | None) -> MagicMock:
    state = MagicMock()
    state.persona = "herta"
    state.last_conversation_time = lct
    return state


def _config(**overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.system_prompt = ""
    cfg.enabled_skills = []
    cfg.brain_monologue_enabled = True
    for name, value in overrides.items():
        setattr(cfg, name, value)
    return cfg


def _fetch(ctx, state, **cfg_overrides) -> list[str]:
    return _fetch_monologue_entries(ctx, state, _config(**cfg_overrides))


def _build_prompt(monologue_entries: list[str]) -> str:
    turn_ctx = ChatTurnContext(session_id="s", user_message="おかえり")
    turn_ctx.monologue_entries = monologue_entries
    PromptBuildStep().run(_ctx(None), _config(), turn_ctx)
    return turn_ctx.system_prompt


def test_injection_when_gap_over_900s_and_entries_exist():
    lct = datetime.now() - timedelta(hours=2)
    old = _event(lct - timedelta(hours=1), "ギャップ前の独り言")
    gap1 = _event(lct + timedelta(minutes=10), "この間、夢の話を考えていた")
    gap2 = _event(lct + timedelta(minutes=30), "次は資料を整理しよう")
    entries = _fetch(_ctx(_fake_repo([old, gap1, gap2])), _state(lct))

    assert entries == ["この間、夢の話を考えていた", "次は資料を整理しよう"]

    prompt = _build_prompt(entries)
    assert "<monologue_context>" in prompt
    assert "この間、夢の話を考えていた" in prompt
    assert "次は資料を整理しよう" in prompt
    assert "ギャップ前の独り言" not in prompt
    assert "再会直後の挨拶" in prompt
    assert "1つまで" in prompt
    repo = _fake_repo([])  # get_by_persona 呼び出し引数の検証
    _fetch(_ctx(repo), _state(lct))
    repo.get_by_persona.assert_called_once_with("herta", "brain.monologue", 10)


def test_no_injection_when_gap_under_900s():
    lct = datetime.now() - timedelta(minutes=5)
    gap = _event(lct + timedelta(minutes=1), "短いギャップ中の独り言")
    entries = _fetch(_ctx(_fake_repo([gap])), _state(lct))

    assert entries == []
    assert "<monologue_context>" not in _build_prompt([])


def test_no_injection_when_all_entries_older_than_gap():
    lct = datetime.now() - timedelta(hours=2)
    old = _event(lct - timedelta(hours=1), "古い独り言")
    entries = _fetch(_ctx(_fake_repo([old])), _state(lct))

    assert entries == []


def test_no_injection_when_disabled():
    lct = datetime.now() - timedelta(hours=2)
    gap = _event(datetime.now() - timedelta(minutes=30), "独り言")
    entries = _fetch(_ctx(_fake_repo([gap])), _state(lct), brain_monologue_enabled=False)

    assert entries == []


def test_no_injection_when_repo_none():
    lct = datetime.now() - timedelta(hours=2)
    entries = _fetch(_ctx(None), _state(lct))

    assert entries == []


def test_no_injection_when_last_conversation_time_none():
    gap = _event(datetime.now(), "独り言")
    entries = _fetch(_ctx(_fake_repo([gap])), _state(None))

    assert entries == []


def test_keeps_last_three_oldest_first():
    lct = datetime.now() - timedelta(hours=2)
    events = [_event(lct + timedelta(minutes=i * 10), f"独り言{i}") for i in range(5)]
    entries = _fetch(_ctx(_fake_repo(events)), _state(lct))

    assert entries == ["独り言2", "独り言3", "独り言4"]


def test_injection_after_static_end():
    prompt = _build_prompt(["独り言A"])

    static_end = prompt.index("__STATIC_END__")
    tag = prompt.index("<monologue_context>")
    assert static_end < tag


def test_tag_pair_no_raw_lt_in_body():
    prompt = _build_prompt(["危険な <script> を含む独り言"])

    start = prompt.index("<monologue_context>")
    end = prompt.index("</monologue_context>")
    body = prompt[start + len("<monologue_context>") : end]
    assert "<" not in body
    assert "＜script＞" in body


def test_no_injection_when_no_entries():
    prompt = _build_prompt([])

    assert "<monologue_context>" not in prompt
