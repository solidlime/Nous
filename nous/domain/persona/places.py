"""場所カタログ — 現在地（``PersonaState.environment``）の語彙と移動コストの基準。

現在地は自由記述 1 個しか無いので、移動の所要時間を測る物差しが要る。各場所に
「自室からの段数（``zone``）」だけを持たせ、移動コストは **出発地と目的地の差** で
決める（固定の所要分を場所に持たせると、近い所から近い所へ行くのに遠回り扱いになる）。

カタログに無い場所も拒否しない。ユーザーが新しい場所を言えば、そこは語彙になる
（``find_place`` が None を返し、呼び出し側が既定の所要分で扱う）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    """拠点の 1 箇所。``zone`` は自室からの段数（移動コストの基準）。"""

    name: str
    slug: str
    zone: int


# ヘルタ宇宙ステーションの初期カタログ。ユーザーが増やせる前提の出発点。
DEFAULT_PLACES: tuple[Place, ...] = (
    Place("自室", "jishitsu", 0),
    Place("ラウンジ", "lounge", 1),
    Place("食堂", "shokudo", 1),
    Place("観測デッキ", "kansoku-deck", 2),
    Place("研究区画", "kenkyu-kukaku", 2),
    Place("格納庫", "kakuno-ko", 3),
    Place("ドック", "dock", 4),
)

DEFAULT_TRAVEL_MINUTES = 10  # カタログに無い場所への既定所要分
MIN_TRAVEL_MINUTES = 2  # 別の場所だが同じ段ならこの程度（同一地点は 0）

_SEPARATORS_RE = re.compile(r"[\s　・/／,，、\-—_]+")


def normalize_place(text: str) -> str:
    """場所名を比較用に正規化する（全角半角の統一・空白/区切りの除去・小文字化）。"""
    stripped = unicodedata.normalize("NFKC", (text or "").strip())
    return _SEPARATORS_RE.sub("", stripped).lower()


def find_place(text: str) -> Place | None:
    """カタログから場所を引く。表記ゆれ（前後空白・全角・大小・区切り）は吸収する。

    slug も ``normalize_place`` に通してから比べる（``kansoku-deck`` のハイフンは
    正規化で消えるため、生の slug と直接比べると一致しない）。
    """
    key = normalize_place(text)
    if not key:
        return None
    for place in DEFAULT_PLACES:
        if key in (normalize_place(place.slug), normalize_place(place.name)):
            return place
    # ``environment`` は自由記述なので「自室。部屋も外も冷えている。」のように
    # 場所名が文中に埋もれる。長い名前から先に見て、部分一致でも引く。
    by_length = sorted(DEFAULT_PLACES, key=lambda p: len(p.name), reverse=True)
    for place in by_length:
        if normalize_place(place.name) in key:
            return place
    return None


def same_place(a: str | None, b: str | None) -> bool:
    """2 つの場所表記が同じ地点を指すか（name↔slug の交差も同一と見なす）。"""
    left = find_place(a or "")
    right = find_place(b or "")
    if left is not None or right is not None:
        # 部分一致で片方だけ解決することはある（「自室。寒い」→自室 vs 未知の場所）。
        return left is not None and right is not None and left.slug == right.slug
    left_key = normalize_place(a or "")
    return bool(left_key) and left_key == normalize_place(b or "")


def travel_minutes(origin: str | None, destination: str | None) -> int:
    """``origin`` から ``destination`` への所要分。同一地点なら 0（コストを課さない）。

    両方がカタログにあれば段数の差 × 5 分（同じ段でも :data:`MIN_TRAVEL_MINUTES`）。
    どちらかがカタログ外なら :data:`DEFAULT_TRAVEL_MINUTES`。

    shortcut: 経路は持たない（自室中心の星型と見なす）。同じ段の場所同士
    （観測デッキ → 研究区画など）も最小 2 分になる。地図を入れる時にここを直す。
    """
    if same_place(origin, destination):
        return 0  # name↔slug の交差表記でも同一地点は 0
    start = find_place(origin or "")
    end = find_place(destination or "")
    if start is None or end is None:
        return DEFAULT_TRAVEL_MINUTES
    return max(MIN_TRAVEL_MINUTES, abs(start.zone - end.zone) * 5)
