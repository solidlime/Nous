"""``_handle_move`` — 移動の生理コストと監査イベント."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nous.application.chat.tools.builtin import _handle_move
from nous.domain.persona.entities import PersonaState
from nous.domain.shared.result import Failure, Success


def _ctx(state: PersonaState | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s1"
    ctx.persona_service.get_context.return_value = Success(
        state or PersonaState(persona="herta", environment="自室", fatigue=0.2, arousal=0.3)
    )
    ctx.persona_service.update_physical_state.return_value = Success(None)
    return ctx


@pytest.fixture(name="rec")
def _record_patch():
    """``place.moved`` の書き込みは別テストで検証する（ここでは実 DB を作らない）。"""
    with patch("nous.application.chat.tools.builtin._record_place_event") as rec:
        yield rec


class TestCost:
    @pytest.mark.asyncio
    async def test_near_move_adds_small_fatigue(self, rec):
        ctx = _ctx()
        r = await _handle_move(ctx, MagicMock(), {"place": "ラウンジ"})

        assert r["status"] == "ok"
        assert r["place"] == "ラウンジ"
        assert r["minutes"] == 5
        # 5 分 * 0.0015 = 0.0075 → 0.2 + 0.0075 = 0.2075 → 丸めて 0.208
        assert r["fatigue"] == pytest.approx(0.208)
        ctx.persona_service.update_physical_state.assert_called_once()
        kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
        assert kwargs["environment"] == "ラウンジ"
        assert kwargs["fatigue"] == pytest.approx(0.2075)
        assert kwargs["arousal"] == pytest.approx(0.303)

    @pytest.mark.asyncio
    async def test_unknown_place_uses_default_ten_minutes(self):
        """カタログ外の場所は既定 10 分。"""
        ctx = _ctx(PersonaState(persona="herta", environment=None, fatigue=0.0, arousal=0.0))
        r = await _handle_move(ctx, MagicMock(), {"place": "月面基地"})

        assert r["minutes"] == 10
        assert r["fatigue_delta"] == pytest.approx(0.015)

    @pytest.mark.asyncio
    async def test_long_travel_caps_fatigue_and_arousal(self):
        """200 分の移動でも疲労 +0.15 / 覚醒 +0.03 で頭打ち（上限はデッド枝にしない）。"""
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=0.0, arousal=0.0))
        with patch("nous.domain.persona.places.travel_minutes", return_value=200):
            r = await _handle_move(ctx, MagicMock(), {"place": "ドック"})

        assert r["fatigue_delta"] == pytest.approx(0.15)
        assert r["arousal_delta"] == pytest.approx(0.03)
        kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
        assert kwargs["fatigue"] == pytest.approx(0.15)
        assert kwargs["arousal"] == pytest.approx(0.03)

    @pytest.mark.asyncio
    async def test_staying_put_costs_nothing_and_records_nothing(self, rec):
        """同じ場所へ「移動」しても課金されず、幻の ``place.moved`` も残らない。"""
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=0.4, arousal=0.4))
        r = await _handle_move(ctx, MagicMock(), {"place": "自室"})

        assert r["minutes"] == 0
        assert r["fatigue"] == pytest.approx(0.4)
        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_name_and_slug_of_same_place_costs_nothing(self, rec):
        """name↔slug の交差表記でも同一地点は 0 分（環境に正式名が入るため必ず起きる）。"""
        ctx = _ctx(PersonaState(persona="herta", environment="観測デッキ", fatigue=0.4, arousal=0.4))
        r = await _handle_move(ctx, MagicMock(), {"place": "kansoku-deck"})

        assert r["minutes"] == 0
        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_nan_state_does_not_become_max_fatigue(self):
        """``float("nan")`` を最大疲労として解釈しない（``min(1.0, nan)`` の罠）。"""
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=float("nan"), arousal=0.0))
        r = await _handle_move(ctx, MagicMock(), {"place": "ラウンジ"})

        assert r["status"] == "ok"
        assert ctx.persona_service.update_physical_state.call_args.kwargs["fatigue"] == pytest.approx(0.0075)

    @pytest.mark.asyncio
    async def test_fatigue_clamped_at_one(self, rec):
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=0.99, arousal=0.0))
        r = await _handle_move(ctx, MagicMock(), {"place": "ドック"})

        assert r["fatigue"] == 1.0
        assert ctx.persona_service.update_physical_state.call_args.kwargs["fatigue"] == 1.0

    @pytest.mark.asyncio
    async def test_never_refuses_even_exhausted(self, rec):
        """助言のみの方針: 疲労 1.0 でも移動は成立する。"""
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=1.0, arousal=1.0))
        r = await _handle_move(ctx, MagicMock(), {"place": "ラウンジ"})

        assert r["status"] == "ok"
        assert "body" in r  # 身体の傾向は返る


class TestPlaces:
    @pytest.mark.asyncio
    async def test_unknown_place_allowed_and_noted(self, rec):
        ctx = _ctx()
        r = await _handle_move(ctx, MagicMock(), {"place": "植物区画"})

        assert r["status"] == "ok"
        assert r["place"] == "植物区画"
        assert "新しい場所" in r["note"]

    @pytest.mark.asyncio
    async def test_catalog_name_normalized(self, rec):
        """表記ゆれはカタログの正式名に寄せる。"""
        ctx = _ctx()
        r = await _handle_move(ctx, MagicMock(), {"place": " ラウンジ　"})

        assert r["place"] == "ラウンジ"

    @pytest.mark.asyncio
    async def test_empty_place_rejected(self, rec):
        r = await _handle_move(_ctx(), MagicMock(), {"place": "  "})
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_persist_failure_surfaces(self, rec):
        ctx = _ctx()
        ctx.persona_service.update_physical_state.return_value = Failure(RuntimeError("db down"))
        r = await _handle_move(ctx, MagicMock(), {"place": "ラウンジ"})
        assert r["status"] == "error"

    @pytest.mark.asyncio
    async def test_unreadable_state_does_not_overwrite(self, rec):
        """``get_context`` が失敗したら書かない（既定値 0.0 で実値を潰さない）。"""
        ctx = _ctx()
        ctx.persona_service.get_context.return_value = Failure(RuntimeError("bad row"))
        r = await _handle_move(ctx, MagicMock(), {"place": "ラウンジ"})

        assert r["status"] == "error"
        ctx.persona_service.update_physical_state.assert_not_called()


class TestAudit:
    @pytest.mark.asyncio
    async def test_event_recorded_with_from_to_and_cost(self, rec):
        ctx = _ctx()
        await _handle_move(ctx, MagicMock(), {"place": "ドック", "reason": "整備"})

        rec.assert_called_once()
        detail = rec.call_args.args[1]
        assert detail["from"] == "自室"
        assert detail["to"] == "ドック"
        assert detail["minutes"] == 20
        assert detail["reason"] == "整備"
        assert detail["known"] is True
        assert detail["fatigue"] == pytest.approx(0.23)

    def test_record_place_event_inserts_row(self):
        """``_record_place_event`` が session_events に 1 行入れる（DB はモック）。"""
        from nous.application.chat.tools.builtin import _record_place_event

        ctx = MagicMock()
        ctx.persona = "herta"
        ctx.session_id = "s1"
        with patch("nous.infrastructure.sqlite.session_event_repo.SessionEventRepository") as repo:
            repo.return_value.insert = MagicMock(return_value=1)
            _record_place_event(ctx, {"from": "自室", "to": "ラウンジ", "minutes": 5})
        repo.assert_called_once()
        event = repo.return_value.insert.call_args.args[0]
        assert event.event_type == "place.moved"
        assert event.persona == "herta"

    def test_record_place_event_swallows_errors(self):
        """監査の失敗で会話を壊さない。"""
        from nous.application.chat.tools.builtin import _record_place_event

        ctx = MagicMock()
        type(ctx).connection = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        _record_place_event(ctx, {"from": "a", "to": "b"})  # 例外を投げない


class TestPlaceSince:
    """ダッシュボード用の滞在時間（直近 ``place.moved`` の時刻）。"""

    def _run(self, events, environment, persona="herta"):
        from unittest.mock import MagicMock, patch

        from nous.api.http.routers.persona.persona_dashboard import _place_since

        ctx = MagicMock()
        ctx.connection = MagicMock()
        with patch(
            "nous.infrastructure.sqlite.session_event_repo.SessionEventRepository.get_by_persona",
            return_value=events,
        ) as get:
            return _place_since(ctx, persona, environment), get

    @staticmethod
    def _event(when, detail):
        from unittest.mock import MagicMock

        event = MagicMock()
        event.timestamp = when
        event.detail = detail
        return event

    def test_returns_latest_event_timestamp(self):
        from datetime import datetime

        when = datetime(2026, 11, 12, 3, 0)
        since, get = self._run([self._event(when, '{"to": "ラウンジ"}')], "ラウンジ")

        assert since == "2026-11-12T03:00:00"
        assert get.call_args.kwargs["event_type"] == "place.moved"
        assert get.call_args.kwargs["limit"] == 1

    def test_mismatched_place_returns_none(self):
        """``update_context`` で場所だけ変えた時、別の場所の到着時刻を出さない。"""
        from datetime import datetime

        since, _ = self._run([self._event(datetime(2026, 11, 9, 3, 0), {"to": "ドック"})], "自室")

        assert since is None  # dict 形式の detail も読める

    def test_slug_and_name_compare_equal(self):
        from datetime import datetime

        when = datetime(2026, 11, 12, 3, 0)
        since, _ = self._run([self._event(when, '{"to": "観測デッキ"}')], "kansoku-deck")

        assert since == "2026-11-12T03:00:00"

    def test_none_when_no_history(self):
        since, _ = self._run([], "自室")
        assert since is None

    def test_fail_soft(self):
        from unittest.mock import MagicMock

        from nous.api.http.routers.persona.persona_dashboard import _place_since

        ctx = MagicMock()
        ctx.connection = None  # SessionEventRepository(None) は AttributeError になる
        assert _place_since(ctx, "herta", None) is None

    def test_none_detail_returns_none(self):
        """detail が NULL の旧行でも落ちない。"""
        from datetime import datetime

        since, _ = self._run([self._event(datetime(2026, 11, 12, 3, 0), None)], "自室")

        assert since is None

    def test_broken_json_detail_returns_none(self):
        from datetime import datetime

        since, _ = self._run([self._event(datetime(2026, 11, 12, 3, 0), "{oops")], "自室")

        assert since is None

    def test_missing_to_key_returns_none(self):
        from datetime import datetime

        since, _ = self._run([self._event(datetime(2026, 11, 12, 3, 0), '{"from": "自室"}')], "自室")

        assert since is None
