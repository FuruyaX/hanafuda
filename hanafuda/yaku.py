"""役の判定と得点計算。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .cards import AKATAN, AME, AOTAN, CHOU, INO, MAKU, SAKAZUKI, SHIKA, TSUKI, Card, Kind


@dataclass(frozen=True)
class Yaku:
    name: str
    points: int


# 役一覧画面用の説明
YAKU_GUIDE: list[tuple[str, int, str]] = [
    ("五光", 10, "光札 5 枚すべて"),
    ("四光", 8, "雨以外の光札 4 枚"),
    ("雨四光", 7, "雨を含む光札 4 枚"),
    ("三光", 5, "雨以外の光札 3 枚"),
    ("猪鹿蝶", 5, "萩に猪・紅葉に鹿・牡丹に蝶"),
    ("花見で一杯", 5, "桜に幕・菊に盃"),
    ("月見で一杯", 5, "芒に月・菊に盃"),
    ("赤短", 5, "松・梅・桜の赤い短冊"),
    ("青短", 5, "牡丹・菊・紅葉の青い短冊"),
    ("タネ", 1, "タネ 5 枚で 1 文、以降 1 枚ごとに +1"),
    ("短冊", 1, "短冊 5 枚で 1 文、以降 1 枚ごとに +1"),
    ("カス", 1, "カス 10 枚で 1 文、以降 1 枚ごとに +1（菊に盃も数える）"),
]


def find_yaku(captured: Iterable[Card]) -> list[Yaku]:
    cards = set(captured)
    result: list[Yaku] = []

    lights = {c for c in cards if c.kind == Kind.HIKARI}
    n_lights = len(lights)
    if n_lights == 5:
        result.append(Yaku("五光", 10))
    elif n_lights == 4:
        result.append(Yaku("雨四光", 7) if AME in lights else Yaku("四光", 8))
    elif n_lights == 3 and AME not in lights:
        result.append(Yaku("三光", 5))

    if {INO, SHIKA, CHOU} <= cards:
        result.append(Yaku("猪鹿蝶", 5))
    if SAKAZUKI in cards:
        if MAKU in cards:
            result.append(Yaku("花見で一杯", 5))
        if TSUKI in cards:
            result.append(Yaku("月見で一杯", 5))
    if AKATAN <= cards:
        result.append(Yaku("赤短", 5))
    if AOTAN <= cards:
        result.append(Yaku("青短", 5))

    n_tane = sum(1 for c in cards if c.kind == Kind.TANE)
    if n_tane >= 5:
        result.append(Yaku("タネ", n_tane - 4))
    n_tan = sum(1 for c in cards if c.kind == Kind.TAN)
    if n_tan >= 5:
        result.append(Yaku("短冊", n_tan - 4))
    n_kasu = sum(1 for c in cards if c.kind == Kind.KASU) + (1 if SAKAZUKI in cards else 0)
    if n_kasu >= 10:
        result.append(Yaku("カス", n_kasu - 9))

    return result


def base_score(captured: Iterable[Card]) -> int:
    return sum(y.points for y in find_yaku(captured))


def final_score(base: int, opponent_called_koikoi: bool) -> int:
    """倍付けを含む最終得点。7 文以上で 2 倍、相手のこいこい中に上がると 2 倍。"""
    score = base
    if base >= 7:
        score *= 2
    if opponent_called_koikoi:
        score *= 2
    return score
