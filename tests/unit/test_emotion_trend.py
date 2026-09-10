"""Tests for emotion trend narrative + context display cleaning."""

from __future__ import annotations

from datetime import timedelta

from nous.domain.persona.emotion_trend import build_emotion_trend_narrative, clean_context
from nous.domain.persona.entities import EmotionRecord
from nous.domain.shared.time_utils import get_now


def _rec(emotion: str, intensity: float, context: str | None, hours_ago: float = 1.0) -> EmotionRecord:
    return EmotionRecord(
        emotion=emotion,
        intensity=intensity,
        timestamp=get_now() - timedelta(hours=hours_ago),
        context=context,
    )


class TestBuildEmotionTrendNarrative:
    def test_transition(self) -> None:
        records = [_rec("sadness", 0.5, "失くした物の話"), _rec("relief", 0.4, "無事の連絡")]
        out = build_emotion_trend_narrative(records, "relief", 0.45)
        assert out.startswith("感情の流れ: ")
        assert "まず sadness（失くした物の話）を感じ" in out
        assert "その後 relief（無事の連絡）へ移った" in out
        assert "いまは relief（やや強い）が続いている。" in out

    def test_fade_to_weak_emotion(self) -> None:
        records = [_rec("joy", 0.8, "プロジェクト完了の報告"), _rec("contentment", 0.2, None)]
        out = build_emotion_trend_narrative(records, "contentment", 0.2)
        assert "joy（プロジェクト完了の報告）を感じていたが" in out
        assert "静かに薄れて落ち着いた" in out
        assert "いまは contentment（弱い）。" in out

    def test_fade_to_neutral(self) -> None:
        records = [_rec("joy", 0.8, "manual_update"), _rec("neutral", 0.0, "manual_update")]
        out = build_emotion_trend_narrative(records, "neutral", 0.0)
        assert "いまは落ち着いている。" in out

    def test_transition_from_neutral(self) -> None:
        """prev=neutral（calm 等の normalize 到達点）からの移行は破文にならない。"""
        records = [_rec("neutral", 0.0, None, hours_ago=4.0), _rec("relief", 0.4, "無事の連絡")]
        out = build_emotion_trend_narrative(records, "relief", 0.45)
        assert out.startswith("感情の流れ: ")
        assert "静かに落ち着いていたが" in out
        assert "relief（無事の連絡）へ移った" in out
        assert "いまは relief（やや強い）。" in out
        assert "neutralを感じ" not in out

    def test_neutral_to_neutral_is_empty(self) -> None:
        records = [_rec("neutral", 0.0, None, hours_ago=4.0), _rec("neutral", 0.0, None)]
        assert build_emotion_trend_narrative(records, "neutral", 0.0) == ""

    def test_fade_elapsed_time_format(self) -> None:
        """減衰文の経過時刻は timestamp 計算（≥24h→日 / ≥1h→時間 / else→分）。"""
        out_day = build_emotion_trend_narrative(
            [_rec("joy", 0.8, None, hours_ago=48.0), _rec("neutral", 0.0, None)], "neutral", 0.0
        )
        assert "2日のうちに" in out_day
        out_min = build_emotion_trend_narrative(
            [_rec("joy", 0.8, None, hours_ago=0.5), _rec("neutral", 0.0, None)], "neutral", 0.0
        )
        assert "30分のうちに" in out_min

    def test_uniform_deepening(self) -> None:
        records = [_rec("loneliness", 0.5, "返信待ち", hours_ago=4.0), _rec("loneliness", 0.5, "返信待ち")]
        out = build_emotion_trend_narrative(records, "loneliness", 0.8)
        assert "loneliness（返信待ち）は続いており、深まっている（やや強い→強い）。" in out

    def test_uniform_easing(self) -> None:
        records = [_rec("anger", 0.8, "argument", hours_ago=4.0), _rec("anger", 0.8, "argument")]
        out = build_emotion_trend_narrative(records, "anger", 0.45)
        assert "和らいでいる（強い→やや強い）。" in out

    def test_uniform_same_label_is_empty(self) -> None:
        records = [_rec("joy", 0.5, "manual_update", hours_ago=4.0), _rec("joy", 0.5, "manual_update")]
        assert build_emotion_trend_narrative(records, "joy", 0.5) == ""

    def test_time_decay_skipped_below_two_points(self) -> None:
        records = [_rec("joy", 0.8, "manual_update"), _rec("neutral", 0.0, "time_decay")]
        assert build_emotion_trend_narrative(records, "joy", 0.8) == ""

    def test_time_decay_skipped_with_enough_points(self) -> None:
        records = [
            _rec("joy", 0.5, "manual_update", hours_ago=3.0),
            _rec("neutral", 0.0, "time_decay", hours_ago=2.0),
            _rec("joy", 0.5, "manual_update", hours_ago=1.0),
        ]
        out = build_emotion_trend_narrative(records, "joy", 0.8)
        assert "time_decay" not in out
        assert "深まっている（やや強い→強い）。" in out

    def test_fewer_than_two_points_is_empty(self) -> None:
        assert build_emotion_trend_narrative([_rec("joy", 0.8, None)], "joy", 0.8) == ""
        assert build_emotion_trend_narrative([], "joy", 0.8) == ""


class TestCleanContext:
    def test_none_and_blank(self) -> None:
        assert clean_context(None) is None
        assert clean_context("   ") is None

    def test_va_json_is_hidden(self) -> None:
        assert clean_context('{"va": [0.6, 0.4]}') is None

    def test_note_json_uses_note(self) -> None:
        assert clean_context('{"va": [0.6], "note": "失くした物の話"}') == "失くした物の話"

    def test_note_json_truncated_at_40(self) -> None:
        note = "あ" * 41
        assert clean_context(f'{{"note": "{note}"}}') == "あ" * 40 + "…"

    def test_plain_text_truncated_at_40(self) -> None:
        assert clean_context("manual_update") == "manual_update"
        assert clean_context("b" * 45) == "b" * 40 + "…"
