"""場所カタログ（``nous/domain/persona/places.py``）と移動コストの回帰ガード."""

from __future__ import annotations

import pytest

from nous.domain.persona.places import (
    DEFAULT_PLACES,
    DEFAULT_TRAVEL_MINUTES,
    find_place,
    normalize_place,
    same_place,
    travel_minutes,
)


class TestNormalize:
    @pytest.mark.parametrize(
        "raw",
        ["自室", " 自室 ", "自室　", "自 室", "自室・", "ＪＩＳＨＩＴＳＵ", "jishitsu", "Jishitsu"],
    )
    def test_variants_collapse(self, raw):
        """表記ゆれ（空白・全角・区切り・大小）を畳む。

        「ＪＩＳＨＩＴＳＵ」は NFKC で小文字化前は全角大文字 → 正規化後に slug と一致する。
        """
        assert normalize_place(raw) in {"自室", "jishitsu"}

    def test_empty(self):
        assert normalize_place("") == ""
        assert normalize_place("   ") == ""


class TestFindPlace:
    def test_by_name_and_slug(self):
        assert find_place("自室").slug == "jishitsu"
        assert find_place("jishitsu").name == "自室"

    @pytest.mark.parametrize(("raw", "name"), [("kansoku-deck", "観測デッキ"), ("kakuno-ko", "格納庫")])
    def test_hyphenated_slug_resolves(self, raw, name):
        """ハイフン入り slug も引ける（正規化でハイフンが消えるため生比較だと落ちる）。"""
        found = find_place(raw)
        assert found is not None and found.name == name

    def test_unknown_is_none(self):
        """カタログ外は None（拒否はしない — 呼び出し側が既定所要分で扱う）。"""
        assert find_place("月面基地") is None

    def test_catalog_has_no_duplicate_zone_zero(self):
        assert sum(1 for p in DEFAULT_PLACES if p.zone == 0) == 1


class TestSamePlace:
    def test_name_and_slug_are_same(self):
        assert same_place("観測デッキ", "kansoku-deck")
        assert same_place("kansoku-deck", "観測デッキ")

    def test_whitespace_and_case(self):
        assert same_place(" ラウンジ ", "らうんじ") is False  # かなは別表記
        assert same_place(" ラウンジ ", "ラウンジ")

    def test_unknown_places_compare_by_text(self):
        assert same_place("植物区画", "植物 区画")
        assert same_place("植物区画", "月面基地") is False

    def test_empty_is_never_same(self):
        assert same_place("", "") is False
        assert same_place(None, None) is False


class TestTravelMinutes:
    def test_same_place_costs_nothing(self):
        """同じ場所へ「移動」してもコストを課さない（繰り返し発話で疲労が溜まらない）。"""
        assert travel_minutes("自室", "自室") == 0
        assert travel_minutes(" ラウンジ ", "ラウンジ") == 0

    def test_zone_distance_scales(self):
        """自室(0)→ラウンジ(1) = 5 分、自室(0)→ドック(4) = 20 分。"""
        assert travel_minutes("自室", "ラウンジ") == 5
        assert travel_minutes("自室", "ドック") == 20
        assert travel_minutes("ドック", "自室") == 20  # 方向に依らない

    def test_name_and_slug_of_same_place_is_zero(self):
        """name↔slug の交差表記でも同一地点は 0（``_handle_move`` が正式名を書くため到達する）。"""
        assert travel_minutes("観測デッキ", "kansoku-deck") == 0
        assert travel_minutes("kansoku-deck", "観測デッキ") == 0

    def test_unknown_place_uses_default(self):
        assert travel_minutes("自室", "月面基地") == DEFAULT_TRAVEL_MINUTES
        assert travel_minutes(None, "自室") == DEFAULT_TRAVEL_MINUTES
