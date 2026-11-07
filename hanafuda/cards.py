"""花札 48 枚の定義。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    HIKARI = "光"
    TANE = "タネ"
    TAN = "短冊"
    KASU = "カス"


# 取り札を並べる順・AI の評価に使う
KIND_ORDER = [Kind.HIKARI, Kind.TANE, Kind.TAN, Kind.KASU]


@dataclass(frozen=True)
class Card:
    id: int  # 0..47
    month: int  # 1..12
    kind: Kind
    name: str  # 札の名前（例: 松に鶴）
    label: str  # 札に表示する短い名前（例: 鶴）
    ribbon: str = ""  # 短冊の色: "red" / "blue" / "plain"

    def __str__(self) -> str:
        return self.name


MONTH_FLOWERS = ["松", "梅", "桜", "藤", "菖蒲", "牡丹", "萩", "芒", "菊", "紅葉", "柳", "桐"]

# (月, 種類, 表示名, 短冊の色)
_SPECS: list[tuple[int, Kind, str, str]] = [
    (1, Kind.HIKARI, "鶴", ""), (1, Kind.TAN, "あかよろし", "red"), (1, Kind.KASU, "", ""), (1, Kind.KASU, "", ""),
    (2, Kind.TANE, "鶯", ""), (2, Kind.TAN, "あかよろし", "red"), (2, Kind.KASU, "", ""), (2, Kind.KASU, "", ""),
    (3, Kind.HIKARI, "幕", ""), (3, Kind.TAN, "みよしの", "red"), (3, Kind.KASU, "", ""), (3, Kind.KASU, "", ""),
    (4, Kind.TANE, "時鳥", ""), (4, Kind.TAN, "短冊", "plain"), (4, Kind.KASU, "", ""), (4, Kind.KASU, "", ""),
    (5, Kind.TANE, "八橋", ""), (5, Kind.TAN, "短冊", "plain"), (5, Kind.KASU, "", ""), (5, Kind.KASU, "", ""),
    (6, Kind.TANE, "蝶", ""), (6, Kind.TAN, "青短", "blue"), (6, Kind.KASU, "", ""), (6, Kind.KASU, "", ""),
    (7, Kind.TANE, "猪", ""), (7, Kind.TAN, "短冊", "plain"), (7, Kind.KASU, "", ""), (7, Kind.KASU, "", ""),
    (8, Kind.HIKARI, "月", ""), (8, Kind.TANE, "雁", ""), (8, Kind.KASU, "", ""), (8, Kind.KASU, "", ""),
    (9, Kind.TANE, "盃", ""), (9, Kind.TAN, "青短", "blue"), (9, Kind.KASU, "", ""), (9, Kind.KASU, "", ""),
    (10, Kind.TANE, "鹿", ""), (10, Kind.TAN, "青短", "blue"), (10, Kind.KASU, "", ""), (10, Kind.KASU, "", ""),
    (11, Kind.HIKARI, "雨", ""), (11, Kind.TANE, "燕", ""), (11, Kind.TAN, "短冊", "plain"), (11, Kind.KASU, "", ""),
    (12, Kind.HIKARI, "鳳凰", ""), (12, Kind.KASU, "", ""), (12, Kind.KASU, "", ""), (12, Kind.KASU, "", ""),
]


def _build_deck() -> list[Card]:
    deck = []
    for i, (month, kind, label, ribbon) in enumerate(_SPECS):
        flower = MONTH_FLOWERS[month - 1]
        if kind == Kind.KASU:
            label = "カス"
        name = f"{flower}に{label}" if kind != Kind.KASU else f"{flower}のカス"
        deck.append(Card(i, month, kind, name, label, ribbon))
    return deck


DECK: list[Card] = _build_deck()
CARDS_BY_ID = {c.id: c for c in DECK}


def find(label: str, month: int) -> Card:
    """月と表示名から札を引く（役判定・テスト用）。"""
    for c in DECK:
        if c.month == month and c.label == label:
            return c
    raise KeyError((label, month))


# 役判定で使う特定の札
TSURU = find("鶴", 1)
MAKU = find("幕", 3)
TSUKI = find("月", 8)
AME = find("雨", 11)
HOUOU = find("鳳凰", 12)
INO = find("猪", 7)
SHIKA = find("鹿", 10)
CHOU = find("蝶", 6)
SAKAZUKI = find("盃", 9)
AKATAN = frozenset(c for c in DECK if c.ribbon == "red")
AOTAN = frozenset(c for c in DECK if c.ribbon == "blue")
