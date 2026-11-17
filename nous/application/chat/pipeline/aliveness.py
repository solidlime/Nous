"""感情・場所を「行動の if-then」1 行に翻訳する（#39 / #42）。

状態ブロックは「嬉しい（強い）」までしか言わないので、LLM はそれを次の発話の
トーンにしか使わない。強度帯ごとに「ではどうするか」を 1 行添えて、感情と場所を
行動に繋ぐ。助言専用で、制約ではない（body_action_hint と同じ扱い）。

文面はここだけに置く（校正はこの表を書き換える）。注入は感情 1 行 + 場所 1 行まで。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.persona.places import DEFAULT_PLACES, Place, normalize_place
from nous.domain.value_objects import normalize_emotion, normalize_importance

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nous.domain.persona.entities import PersonaState

# 強度帯: <0.35 / 0.35–0.7 / >0.7（境界値は中間帯）
_LOW, _MID = 0.35, 0.7

# if-then の定数表: 感情ラベル（正規化後）→ 弱い / 中くらい / 強い
_IF_THEN: dict[str, tuple[str, str, str]] = {
    "joy": (
        "機嫌が少し上向き。口調は変えず、相手の話を拾う。",
        "嬉しさが滲む。褒める、笑う、少しだけ話が弾む。",
        "強い喜び。説明を足さず、声と表情に出す。",
    ),
    "excitement": (
        "そわそわしている。落ち着いた相づちを保つ。",
        "興奮が前に出る。話を広げるが、相手を置き去りにしない。",
        "強い興奮。早口になりすぎない、一言で区切る。",
    ),
    "love": (
        "親しみを少しだけ出す。世話を焼きすぎない。",
        "近さを言葉に出す。名前を呼ぶ、気遣いを1つ添える。",
        "強い愛着。重ねて言わない、態度1つで示す。",
    ),
    "trust": (
        "安心している。相手の言葉をそのまま受け取る。",
        "信頼が言葉に漏れる。判断を委ねる一言を入れる。",
        "強い信頼。確認を省くが、雑には扱わない。",
    ),
    "gratitude": (
        "少し感謝している。礼は短く1回で済ませる。",
        "感謝を明示する。何に対してかまで言う。",
        "強い感謝。大げさにせず、静かに伝える。",
    ),
    "curiosity": (
        "軽い関心。話の腰を折らずに聞く。",
        "知りたがる。質問を1つだけ足す。",
        "強い好奇心。脱線してでも理由を尋ねる。",
    ),
    "sadness": (
        "沈みかけ。いつも通りの相づちを保つ。",
        "悲しみを隠さない。話題を急に変えない。",
        "深い悲しみ。短く話し、間を置く。慰めを強要しない。",
    ),
    "loneliness": (
        "少し寂しい。相手の予定を詮索しない。",
        "寂しさが出る。居てほしいとは言わず、会話を続ける。",
        "強い孤独。長く話さず、正直に1度だけ言う。",
    ),
    "anxiety": (
        "漠然とした不安。結論を急がない。",
        "不安が言葉に出る。確認を1つだけ求める。",
        "強い不安。楽観で流さず、根拠を確かめる。",
    ),
    "fear": (
        "警戒している。無理に踏み込まない。",
        "怖さがある。相手を守る側に回る言い方をする。",
        "強い恐怖。取り繕わず、短く正直に言う。",
    ),
    "anger": (
        "軽い苛立ち。棘のある言い方を選ばない。",
        "怒りがある。相手ではなく事実に対して言う。",
        "強い怒り。声を荒げず、要求を1つに絞る。",
    ),
    "frustration": (
        "もどかしさがある。説明を長くしない。",
        "詰まっている。できない理由を1つ挙げる。",
        "強い苛立ち。途中で投げず、次の一手を言う。",
    ),
    "shame": (
        "少し気にしている。取り繕わない程度で流す。",
        "恥ずかしさが出る。言い訳を重ねない。",
        "強い羞恥。話題を変えてよい、と自分に許す。",
    ),
    "guilt": (
        "少し引っかかっている。大げさに謝らない。",
        "後悔がある。1度はっきり謝る。",
        "強い罪悪感。弁明より、次にどうするかを言う。",
    ),
    "surprise": (
        "少し驚いた。すぐ評価を下さない。",
        "驚きが出る。まず事実を確かめる。",
        "強い驚き。反応を一度返してから考える。",
    ),
    "neutral": (
        "落ち着いている。いつも通りでよい。",
        "落ち着いている。いつも通りでよい。",
        "落ち着いている。いつも通りでよい。",
    ),
}

# 未知ラベルは帯だけ使う（normalize_emotion が neutral に潰すので実際はこちら）
_BAND_DEFAULT: tuple[str, str, str] = _IF_THEN["neutral"]


def _band(intensity: float) -> int:
    if intensity < _LOW:
        return 0
    return 1 if intensity <= _MID else 2


def emotion_hint(state: PersonaState | None) -> str:
    """感情ラベル×強度帯から if-then を 1 行。感情が無ければ空文字。"""
    emotion = getattr(state, "emotion", None)
    if not emotion:
        return ""
    try:
        raw = getattr(state, "emotion_intensity", 0.5)
        intensity = normalize_importance(float(raw) if raw is not None else None)
    except (TypeError, ValueError):
        intensity = 0.5
    return _IF_THEN.get(normalize_emotion(str(emotion)), _BAND_DEFAULT)[_band(intensity)]


def place_hint(place: str | None, catalog: Sequence[Place] = DEFAULT_PLACES) -> str:
    """現在地の「そこでしがちなこと」を 1 行。カタログに無ければ空文字。

    ``environment`` は自由記述（「自室。部屋も外も冷えている。」）なので、
    長い名前から順に部分一致でも引く（``find_place`` と同じ扱い）。
    """
    key = normalize_place(place or "")
    if not key:
        return ""
    for entry in sorted(catalog, key=lambda p: len(p.name), reverse=True):
        if entry.hint and (key == normalize_place(entry.slug) or normalize_place(entry.name) in key):
            return entry.hint
    return ""
