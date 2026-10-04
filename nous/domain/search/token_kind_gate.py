"""dominantTokenKind 判定 + FTS OR-fallback 用 bm25 バー（純関数）。

item 5（実測: research/nous-search-eval-20260928/item5_threshold_design.md）:
FTS の OR-fallback で semantic merge に紛れ込む弱マッチを bm25 バーで静かに
窓から落とす。バーはクエリの dominantTokenKind（bigram / word / mixed）別に引く。

判定・閾値は実測スクリプト（_tmp_item5_measure2.py）と同一定義:
  cjk_tok = CJK 文字を含むトークン数
  lat_tok = latin 文字のみのトークン数（CJK を含まないものに限る）
  kind = bigram if lat==0 / word if cjk==0 / bigram if cjk>=lat else word
         （both 0 → mixed = ゲート無効）

``search_fts`` は raw bm25 ではなく正規化スコア ``|bm25|/(1+|bm25|)`` を返す。
``|bm25| >= bar`` は ``score >= bar/(1+bar)`` と同値（単調変換）なので、
ゲートは正規化スコア上で等価に適用できる。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

KIND_BIGRAM = "bigram"
KIND_WORD = "word"
KIND_MIXED = "mixed"

# 既定バー（実測推奨値 :: bigram -2.0 / word -2.0 の絶対値）。符号管理は bar 側
# （正の大きさで保持し、適用時に ``bm25 <= -bar`` と解釈する）。
DEFAULT_INJECTION_MAX_BM25: dict[str, float] = {KIND_BIGRAM: 2.0, KIND_WORD: 2.0}


def _is_cjk_char(ch: str) -> bool:
    return "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff"


def _cjk_len(s: str) -> int:
    return sum(1 for ch in s if _is_cjk_char(ch))


def _latin_len(s: str) -> int:
    return sum(1 for ch in s if ch.isascii() and ch.isalpha())


def classify_token_kind(tokens: Iterable[str]) -> str:
    """Sudachi トークン列の文字種比から dominantTokenKind を返す。

    both 0（トークン無し / 非 CJK・非 latin）は ``"mixed"`` = ゲート無効。
    """
    cjk_tok = 0
    lat_tok = 0
    for t in tokens:
        c = _cjk_len(t)
        if c > 0:
            cjk_tok += 1
        elif _latin_len(t) > 0:
            lat_tok += 1
    if cjk_tok == 0 and lat_tok == 0:
        return KIND_MIXED
    if lat_tok == 0:
        return KIND_BIGRAM
    if cjk_tok == 0:
        return KIND_WORD
    return KIND_BIGRAM if cjk_tok >= lat_tok else KIND_WORD


def bar_for_tokens(tokens: Iterable[str], bars: Mapping[str, float]) -> float | None:
    """クエリのトークン種別に対応するバー（正の大きさ）を返す。

    mixed / 未設定 / 非正値は ``None`` = バー適用なし（全候補通過）。
    """
    bar = bars.get(classify_token_kind(tokens))
    if bar is None or bar <= 0.0:
        return None
    return bar


def normalized_threshold(bar: float) -> float:
    """raw bm25 バー ``|bm25| >= bar`` を正規化スコア閾値へ変換する。"""
    return bar / (1.0 + bar)


def passes_bm25_bar(normalized_score: float, bar: float) -> bool:
    """正規化 bm25 スコアがバーを通過するか（``bm25 <= -bar`` と等価）。"""
    return normalized_score >= normalized_threshold(bar)
