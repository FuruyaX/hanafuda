"""札を合わせて取るゲームの共通進行と、こいこい（2 人）。UI はメソッドを呼んで状態を描画するだけ。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .cards import DECK, Card
from .yaku import Yaku, base_score, final_score, find_yaku


class Phase(Enum):
    PLAY = "play"  # 手札を出す
    CHOOSE_HAND = "choose_hand"  # 出した札で取る場札を選ぶ（候補 2 枚）
    CHOOSE_DRAW = "choose_draw"  # めくった札で取る場札を選ぶ（候補 2 枚）
    KOIKOI = "koikoi"  # 勝負 / こいこい の選択（こいこいのみ）
    ROUND_OVER = "round_over"
    GAME_OVER = "game_over"


class GameError(Exception):
    pass


@dataclass
class Player:
    name: str
    hand: list[Card] = field(default_factory=list)
    captured: list[Card] = field(default_factory=list)
    score: int = 0  # 対局の合計
    koikoi: bool = False  # この月にこいこいした（こいこいのみ）
    stop_base: int = 0  # 最後に判断したときの基本点（こいこいのみ）


@dataclass
class RoundResult:
    month: int
    deltas: list[int]  # 各プレイヤーの得点増減


@dataclass
class KoikoiResult(RoundResult):
    winner: int | None = None  # None は流れ
    yaku: list[Yaku] = field(default_factory=list)
    base: int = 0
    points: int = 0


class MatchingGame:
    """手札を出し、山札をめくり、同じ月の札を取る ― こいこい・花合わせ共通の進行。"""

    TITLE = ""
    HAND_SIZE = 8
    FIELD_SIZE = 8

    def __init__(self, months: int, names: tuple[str, ...], rng: random.Random | None = None,
                 dealer: int | None = None):
        self.rng = rng or random.Random()
        self.months = months
        self.players = [Player(n) for n in names]
        self.dealer = self.rng.randrange(len(names)) if dealer is None else dealer
        self.month = 1
        self.results: list[RoundResult] = []
        self.log: list[str] = []
        self._start_round()

    # ---- 状態参照 ----
    @property
    def player(self) -> Player:
        return self.players[self.current]

    def matches(self, card: Card) -> list[Card]:
        return [c for c in self.field if c.month == card.month]

    def winner(self) -> int | None:
        scores = [p.score for p in self.players]
        best = max(scores)
        return scores.index(best) if scores.count(best) == 1 else None

    # ---- 操作 ----
    def play(self, card_id: int) -> None:
        """手札を 1 枚出す。"""
        self._expect(Phase.PLAY)
        card = next((c for c in self.player.hand if c.id == card_id), None)
        if card is None:
            raise GameError("手札にない札です")
        self.player.hand.remove(card)
        self.last_played = card
        self.last_drawn = None
        self._log(f"{self.player.name}: {card} を出す")
        self._place(card, from_hand=True)

    def choose(self, field_card_id: int) -> None:
        """候補が 2 枚あるとき、取る場札を選ぶ。"""
        if self.phase not in (Phase.CHOOSE_HAND, Phase.CHOOSE_DRAW):
            raise GameError(f"今は選べません（{self.phase.value}）")
        assert self.pending is not None
        target = next((c for c in self.matches(self.pending) if c.id == field_card_id), None)
        if target is None:
            raise GameError("その札は取れません")
        from_hand = self.phase == Phase.CHOOSE_HAND
        self._capture([self.pending, target])
        self.pending = None
        self._after_place(from_hand)

    def next_round(self) -> None:
        self._expect(Phase.ROUND_OVER)
        if self.month >= self.months:
            self.phase = Phase.GAME_OVER
            return
        self.month += 1
        self._start_round()

    # ---- 派生クラスで決めること ----
    def _on_deal(self) -> None:
        """配り終えたとき（手役の判定など）。"""

    def _end_turn(self) -> None:
        self._next_turn()

    def _on_exhausted(self) -> None:
        """全員の手札がなくなったとき。"""
        raise NotImplementedError

    # ---- 共通処理 ----
    def _start_round(self) -> None:
        n = len(self.players)
        while True:
            deck = list(DECK)
            self.rng.shuffle(deck)
            field_cards = deck[:self.FIELD_SIZE]
            months = [c.month for c in field_cards]
            if all(months.count(m) < 4 for m in set(months)):
                break  # 場に同じ月が 4 枚あれば配り直し
        self.field = field_cards
        rest = deck[self.FIELD_SIZE:]
        for i, p in enumerate(self.players):
            p.hand = sorted(rest[i * self.HAND_SIZE:(i + 1) * self.HAND_SIZE], key=lambda c: c.id)
            p.captured = []
            p.koikoi = False
            p.stop_base = 0
        self.deck = rest[n * self.HAND_SIZE:]
        self.current = self.dealer
        self.phase = Phase.PLAY
        self.pending: Card | None = None
        self.last_played: Card | None = None
        self.last_drawn: Card | None = None
        self.last_result: RoundResult | None = None
        self._log(f"--- {self.month} 月目（親: {self.players[self.dealer].name}）---")
        self._on_deal()

    def _expect(self, phase: Phase) -> None:
        if self.phase != phase:
            raise GameError(f"今は {phase.value} ではありません（{self.phase.value}）")

    def _log(self, text: str) -> None:
        self.log.append(text)

    def _capture(self, cards: list[Card]) -> None:
        for c in cards:
            if c in self.field:
                self.field.remove(c)
        self.player.captured.extend(cards)
        self._log(f"{self.player.name}: {'・'.join(map(str, cards))} を取る")

    def _place(self, card: Card, from_hand: bool) -> None:
        """札を場に出し、同じ月があれば取る。候補が 2 枚なら選択待ちにする。"""
        m = self.matches(card)
        if len(m) == 2:
            self.pending = card
            self.phase = Phase.CHOOSE_HAND if from_hand else Phase.CHOOSE_DRAW
            return
        if m:  # 1 枚、または 3 枚（全部取る）
            self._capture([card, *m])
        else:
            self.field.append(card)
        self._after_place(from_hand)

    def _after_place(self, from_hand: bool) -> None:
        if from_hand:
            card = self.deck.pop()
            self.last_drawn = card
            self._log(f"{self.player.name}: 山札から {card} をめくる")
            self._place(card, from_hand=False)
        else:
            self._end_turn()

    def _next_turn(self) -> None:
        if all(not p.hand for p in self.players):
            self._on_exhausted()
            return
        self.current = (self.current + 1) % len(self.players)
        self.phase = Phase.PLAY

    def _record(self, result: RoundResult) -> None:
        for p, d in zip(self.players, result.deltas):
            p.score += d
        self.results.append(result)
        self.last_result = result
        self.phase = Phase.ROUND_OVER


class Game(MatchingGame):
    """こいこい（2 人）。役ができたら勝負かこいこいを選ぶ。"""

    TITLE = "こいこい"

    def __init__(self, months: int = 6, names: tuple[str, str] = ("あなた", "CPU"),
                 rng: random.Random | None = None, dealer: int | None = None):
        super().__init__(months, names, rng, dealer)

    @property
    def opponent(self) -> Player:
        return self.players[1 - self.current]

    def decide(self, koikoi: bool) -> None:
        """役ができたときの判断。False で勝負（この月を終える）。"""
        self._expect(Phase.KOIKOI)
        if not koikoi:
            self._log(f"{self.player.name}: 勝負！")
            self._finish_round(self.current)
            return
        self._log(f"{self.player.name}: こいこい！")
        self.player.koikoi = True
        self.player.stop_base = base_score(self.player.captured)
        self._next_turn()

    def _end_turn(self) -> None:
        p = self.player
        base = base_score(p.captured)
        if base > p.stop_base:
            names = "・".join(y.name for y in find_yaku(p.captured))
            self._log(f"{p.name}: 役ができた（{names}）")
            if not p.hand:  # 手札がなければこいこいできない
                self._finish_round(self.current)
            else:
                self.phase = Phase.KOIKOI
            return
        self._next_turn()

    def _on_exhausted(self) -> None:
        self._finish_round(None)

    def _finish_round(self, winner: int | None) -> None:
        if winner is None:
            self._log("流れ（引き分け）")
            self._record(KoikoiResult(self.month, [0, 0]))
            return
        w = self.players[winner]
        yaku = find_yaku(w.captured)
        base = sum(y.points for y in yaku)
        points = final_score(base, self.players[1 - winner].koikoi)
        deltas = [0, 0]
        deltas[winner] = points
        self.dealer = winner
        self._log(f"{w.name}: {points} 文獲得")
        self._record(KoikoiResult(self.month, deltas, winner, yaku, base, points))
