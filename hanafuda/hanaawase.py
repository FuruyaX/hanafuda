"""花合わせ（勝負するのは 3 人。参加は 3〜12 人）。手札がなくなるまで取り合い、札の点数・出来役・手役で精算する。

点数や役の値は仮のもの。ルールを変えるときはこのファイルの定数だけ直せばよい。
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .cards import AKATAN, AME, AOTAN, CHOU, INO, MAKU, SAKAZUKI, SHIKA, TSUKI, Card, Kind
from .game import MatchingGame, RoundResult
from .yaku import Yaku

CARD_POINTS = {Kind.HIKARI: 20, Kind.TANE: 10, Kind.TAN: 5, Kind.KASU: 1}
TOTAL_POINTS = 264  # 48 枚の合計
PLAYERS = 3  # 勝負する人数
BASELINE = TOTAL_POINTS // PLAYERS  # 88 点を超えた分が勝ち
FOLD_FEE = 5  # 降りた人が勝負した 1 人に払う点

# 出来役（取り札でそろえる）。値は他の 2 人から 1 人ずつ受け取る
DEKIYAKU_POINTS = {
    "五光": 200, "四光": 60, "三光": 20,
    "七短": 40, "六短": 30, "赤短": 20, "青短": 20,
    "猪鹿蝶": 20, "花見で一杯": 20, "月見で一杯": 20,
}
# 手役（配られた手札 7 枚でできている役）。同じく他の 2 人から受け取る
TEYAKU_POINTS = {"手四": 20, "三本": 10, "光一": 20, "短一": 20, "空素": 20}

RULE_GUIDE: list[tuple[str, str, str]] = [
    ("札の点数", "光 20 / タネ 10 / 短冊 5 / カス 1", "合計 264。88 点を超えた分がプラス"),
    ("五光", "200", "光札 5 枚"),
    ("四光", "60", "光札 4 枚"),
    ("三光", "20", "雨以外の光札 3 枚"),
    ("七短 / 六短", "40 / 30", "短冊 7 枚以上 / 6 枚"),
    ("赤短・青短", "各 20", "赤い短冊 3 枚 / 青い短冊 3 枚"),
    ("猪鹿蝶", "20", "萩に猪・紅葉に鹿・牡丹に蝶"),
    ("花見で一杯・月見で一杯", "各 20", "桜に幕 / 芒に月 と 菊に盃"),
    ("手四（手役）", "20", "配られた手札に同じ月が 4 枚"),
    ("三本（手役）", "10", "同じ月が 3 枚（1 組ごと）"),
    ("光一・短一（手役）", "各 20", "光（短冊）1 枚と残り 6 枚がカス"),
    ("空素（手役）", "20", "手札 7 枚すべてカス"),
    ("降り賃", f"{FOLD_FEE} × 3", f"4 人以上で降りた人は、勝負した 3 人に {FOLD_FEE} 点ずつ払う"),
]


def card_points(cards: Iterable[Card]) -> int:
    return sum(CARD_POINTS[c.kind] for c in cards)


def find_dekiyaku(captured: Iterable[Card]) -> list[Yaku]:
    cards = set(captured)
    result: list[Yaku] = []

    def add(name: str) -> None:
        result.append(Yaku(name, DEKIYAKU_POINTS[name]))

    lights = {c for c in cards if c.kind == Kind.HIKARI}
    if len(lights) == 5:
        add("五光")
    elif len(lights) == 4:
        add("四光")
    elif len(lights) == 3 and AME not in lights:
        add("三光")

    n_tan = sum(1 for c in cards if c.kind == Kind.TAN)
    if n_tan >= 7:
        add("七短")
    elif n_tan == 6:
        add("六短")
    if AKATAN <= cards:
        add("赤短")
    if AOTAN <= cards:
        add("青短")
    if {INO, SHIKA, CHOU} <= cards:
        add("猪鹿蝶")
    if SAKAZUKI in cards and MAKU in cards:
        add("花見で一杯")
    if SAKAZUKI in cards and TSUKI in cards:
        add("月見で一杯")
    return result


def find_teyaku(hand: Iterable[Card]) -> list[Yaku]:
    cards = list(hand)
    result: list[Yaku] = []
    for _, n in sorted(Counter(c.month for c in cards).items()):
        if n == 4:
            result.append(Yaku("手四", TEYAKU_POINTS["手四"]))
        elif n == 3:
            result.append(Yaku("三本", TEYAKU_POINTS["三本"]))
    kinds = Counter(c.kind for c in cards)
    if kinds[Kind.KASU] == len(cards):
        result.append(Yaku("空素", TEYAKU_POINTS["空素"]))
    elif kinds[Kind.KASU] == len(cards) - 1:
        if kinds[Kind.HIKARI] == 1:
            result.append(Yaku("光一", TEYAKU_POINTS["光一"]))
        elif kinds[Kind.TAN] == 1:
            result.append(Yaku("短一", TEYAKU_POINTS["短一"]))
    return result


@dataclass
class PlayerTally:
    card_points: int
    dekiyaku: list[Yaku]
    teyaku: list[Yaku]
    delta: int

    @property
    def yaku_total(self) -> int:
        return sum(y.points for y in self.dekiyaku + self.teyaku)


@dataclass
class HanaawaseResult(RoundResult):
    tallies: list[PlayerTally] = field(default_factory=list)  # 勝負した人（active 順）


def settle(card_pts: list[int], yaku_totals: list[int]) -> list[int]:
    """札点は 88 との差。役は持ち主が他の全員から 1 人分ずつ受け取る（合計は常に 0）。"""
    n = len(card_pts)
    total = sum(yaku_totals)
    return [
        (card_pts[i] - BASELINE) + yaku_totals[i] * (n - 1) - (total - yaku_totals[i])
        for i in range(n)
    ]


class HanaawaseGame(MatchingGame):
    MODE = "hanaawase"
    TITLE = "花合わせ"
    SEATS = PLAYERS
    HAND_SIZE = 7
    FIELD_SIZE = 6
    FOLD_FEE = FOLD_FEE

    def __init__(self, months: int = 6, names: tuple[str, ...] = ("あなた", "CPU 1", "CPU 2"),
                 rng: random.Random | None = None, dealer: int | None = None):
        super().__init__(months, names, rng, dealer)

    def _on_deal(self) -> None:
        self.teyaku = {i: find_teyaku(self.players[i].hand) for i in self.active}

    def _on_exhausted(self) -> None:
        players = [self.players[i] for i in self.active]
        pts = [card_points(p.captured) for p in players]
        deki = [find_dekiyaku(p.captured) for p in players]
        teyaku = [self.teyaku[i] for i in self.active]
        totals = [sum(y.points for y in d + t) for d, t in zip(deki, teyaku)]
        active_deltas = settle(pts, totals)
        tallies = [PlayerTally(*row) for row in zip(pts, deki, teyaku, active_deltas)]
        month, deltas, active, folded, fee = self._new_result_args()
        for i, d in zip(self.active, active_deltas):
            deltas[i] = d
        self._log("勝負した全員の手札がなくなりました。精算します")
        self._record(HanaawaseResult(month, deltas, active, folded, fee, tallies))
        self.dealer = (self.dealer + 1) % len(self.players)  # 親は順番に回す
