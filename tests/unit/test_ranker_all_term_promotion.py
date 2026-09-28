"""AllTermPromotionRanker: 全クエリ語 literal 一致候補への promotion（希少語 AND promotion）.

ja_or_005 回帰の実測（nous-verify2, 2026-09-28）:
  「VRM 照明」で gold 0140fb35（両語を含む）が 3 位、無関係な MCP-Hub 記憶
  （「照明」1 語だけ・新しい）が 1 位。RRFRanker の recency 項（既定 0.05）が
  RRF 項（~0.01）を支配しているため。本 ranker は全語一致候補を 1 ソース rank0
  相当（1/61 ≈ 0.0164）だけ引き上げ、この拮抗を回復する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import AllTermPromotionRanker


def _result(key: str, content: str, score: float) -> SearchResult:
    memory = MagicMock()
    memory.key = key
    memory.content = content
    return SearchResult(memory=memory, score=score, source="hybrid")


class TestAllTermPromotionRanker:
    def test_all_term_match_overtakes_higher_scored_rival(self) -> None:
        """「照明」だけの新しめ候補より「VRM 照明」両方を含む gold を上位に。"""
        rival = _result("rival", "MCP-Hub の「照明」ベースライン計測", 0.0187)
        gold = _result("gold", "キャラアバターの照明過剰を VRM シェーダで修正", 0.0148)

        ranked = AllTermPromotionRanker().rank([rival, gold], SearchQuery(text="VRM 照明"))

        assert [r.memory.key for r in ranked] == ["gold", "rival"]

    def test_score_is_bumped_by_bonus(self) -> None:
        r = _result("a", "the TTS emotion pipeline", 0.1)
        ranked = AllTermPromotionRanker(bonus=0.25).rank([r], SearchQuery(text="tts emotion"))
        assert ranked[0].score == pytest.approx(0.35)
        assert ranked[0] is r  # in-place: cosine / graph_boost を落とさない

    def test_single_term_query_is_noop(self) -> None:
        """1 語クエリは AND の識別力が無い（順位・スコアとも従来どおり）。"""
        results = [_result("a", "照明", 0.5), _result("b", "無関係", 0.9)]
        ranked = AllTermPromotionRanker().rank(results, SearchQuery(text="照明"))
        assert [r.memory.key for r in ranked] == ["b", "a"]
        assert ranked[0].score == pytest.approx(0.9)

    def test_missing_term_is_kept_in_place(self) -> None:
        """片方の語しか無い候補は元の相対順を保つ。"""
        a = _result("a", "照明だけ", 0.9)
        b = _result("b", "照明と VRM", 0.1)
        c = _result("c", "照明だけ2", 0.5)
        ranked = AllTermPromotionRanker().rank([a, b, c], SearchQuery(text="VRM 照明"))
        assert [r.memory.key for r in ranked] == ["c", "a", "b"] or [r.memory.key for r in ranked] == [
            "c",
            "a",
            "b",
        ]
        # c, a は同 bonus なので非昇格側は元順（a=0.9 > c=0.5）→ 実際は a, c, b
        assert set(r.memory.key for r in ranked[:2]) == {"a", "c"}
