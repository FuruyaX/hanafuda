"""札を合わせて取るゲームの共通進行と、こいこい。UI はメソッドを呼んで状態を描画するだけ。

参加者は最大 12 人。実際に札を持って戦うのは SEATS 人（こいこい 2 / 花合わせ 3）で、
毎月、親から順に「勝負 / 降り」を決めて絞る。
- 参加者数が SEATS の倍数なら、配られた手札を見てから決める（降りたら手札は山に戻す）
- 倍数でなければ、手札なしで決める
- 残りの人数と空き席が同じになったら、残りは強制的に勝負
- 降りた人は、勝負した各人に降り賃（FOLD_FEE）を払う。決める前に席が埋まった人は見学（払わない）
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .cards import DECK, Card
from .yaku import Yaku, base_score, final_score, find_yaku

MAX_PLAYERS = 12


class Phase(Enum):
    DECLARE = "declare"  # 勝負 / 降り の選択
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
    folded: bool = False  # この月は自分で降りた（降り賃を払う）
    koikoi: bool = False  # この月にこいこいした（こいこいのみ）
    stop_base: int = 0  # 最後に判断したときの基本点（こいこいのみ）


@dataclass
class RoundResult:
    month: int
    deltas: list[int]  # 参加者ごとの得点増減（降り賃を含む）
    active: list[int]  # 勝負した人
    folded: list[int]  # 自分で降りた人（勝負しなかった残りは見学）
    fold_fee: int  # 降りた人が勝負した 1 人に払う額


@dataclass
class KoikoiResult(RoundResult):
    winner: int | None = None  # None は流れ
    yaku: list[Yaku] = field(default_factory=list)
    base: int = 0
    points: int = 0


class MatchingGame:
    """手札を出し、山札をめくり、同じ月の札を取る ― こいこい・花合わせ共通の進行。"""

    MODE = ""
    TITLE = ""
    SEATS = 2
    HAND_SIZE = 8
    FIELD_SIZE = 8
    FOLD_FEE = 1

    def __init__(self, months: int, names: tuple[str, ...], rng: random.Random | None = None,
                 dealer: int | None = None):
        if not self.SEATS <= len(names) <= MAX_PLAYERS:
            raise ValueError(f"{self.TITLE}は {self.SEATS}〜{MAX_PLAYERS} 人です")
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

    @property
    def sees_hand_on_declare(self) -> bool:
        """参加者数が席数の倍数なら、手札を見てから勝負 / 降りを決める。"""
        return len(self.players) % self.SEATS == 0

    def matches(self, card: Card) -> list[Card]:
        return [c for c in self.field if c.month == card.month]

    def winner(self) -> int | None:
        scores = [p.score for p in self.players]
        best = max(scores)
        return scores.index(best) if scores.count(best) == 1 else None

    # ---- 操作 ----
    def declare(self, play: bool) -> None:
        """勝負（True）か降り（False）か。"""
        self._expect(Phase.DECLARE)
        p = self.player
        if play:
            self.active.append(self.current)
            self._log(f"{p.name}: 勝負")
        else:
            p.folded = True
            self.deck.extend(p.hand)  # 見た手札は山に戻して切り直す
            p.hand = []
            self.rng.shuffle(self.deck)
            self._log(f"{p.name}: 降り")
        self.declare_pos += 1
        self._advance_declare()

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
        """勝負した全員の手札がなくなったとき。"""
        raise NotImplementedError

    # ---- 勝負 / 降り ----
    def _start_round(self) -> None:
        n = len(self.players)
        for p in self.players:
            p.hand, p.captured = [], []
            p.folded = p.koikoi = False
            p.stop_base = 0
        self.deck = list(DECK)
        self.rng.shuffle(self.deck)
        self.field: list[Card] = []
        self.active: list[int] = []
        self.order = [(self.dealer + i) % n for i in range(n)]  # 親から順に
        self.declare_pos = 0
        self.pending: Card | None = None
        self.last_played: Card | None = None
        self.last_drawn: Card | None = None
        self.last_result: RoundResult | None = None
        self.phase = Phase.DECLARE
        self._log(f"--- {self.month} 月目（親: {self.players[self.dealer].name}）---")
        self._advance_declare()

    def _deal_hand(self, index: int) -> None:
        p = self.players[index]
        p.hand = sorted(self.deck[:self.HAND_SIZE], key=lambda c: c.id)
        del self.deck[:self.HAND_SIZE]

    def _advance_declare(self) -> None:
        forced_any = False
        while len(self.active) < self.SEATS:
            index = self.order[self.declare_pos]
            remaining = len(self.order) - self.declare_pos
            if self.sees_hand_on_declare:
                self._deal_hand(index)
            if remaining == self.SEATS - len(self.active):  # 残り全員が強制的に勝負
                self.active.append(index)
                self.declare_pos += 1
                forced_any = True
                continue
            self.current = index
            self.phase = Phase.DECLARE
            return
        if forced_any and len(self.players) > self.SEATS:
            self._log("残りの人は強制的に勝負")
        self._deal_rest()

    def _deal_rest(self) -> None:
        if not self.sees_hand_on_declare:
            for index in self.active:
                self._deal_hand(index)
        while True:  # 場に同じ月が 4 枚なら配り直し
            months = [c.month for c in self.deck[:self.FIELD_SIZE]]
            if all(months.count(m) < 4 for m in set(months)):
                break
            self.rng.shuffle(self.deck)
        self.field = self.deck[:self.FIELD_SIZE]
        del self.deck[:self.FIELD_SIZE]
        self.current = self.active[0]
        self.phase = Phase.PLAY
        names = "・".join(self.players[i].name for i in self.active)
        self._log(f"勝負: {names}")
        self._on_deal()

    # ---- 共通処理 ----
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
        if all(not self.players[i].hand for i in self.active):
            self._on_exhausted()
            return
        pos = self.active.index(self.current)
        self.current = self.active[(pos + 1) % len(self.active)]
        self.phase = Phase.PLAY

    def _record(self, result: RoundResult) -> None:
        """月の結果を記録する。降り賃を加えてから合計に足す。"""
        for f in result.folded:
            result.deltas[f] -= self.FOLD_FEE * len(result.active)
        for a in result.active:
            result.deltas[a] += self.FOLD_FEE * len(result.folded)
        for p, d in zip(self.players, result.deltas):
            p.score += d
        self.results.append(result)
        self.last_result = result
        self.phase = Phase.ROUND_OVER

    def _new_result_args(self) -> tuple[int, list[int], list[int], list[int], int]:
        folded = [i for i, p in enumerate(self.players) if p.folded]
        return self.month, [0] * len(self.players), list(self.active), folded, self.FOLD_FEE


class Game(MatchingGame):
    """こいこい。役ができたら勝負かこいこいを選ぶ。"""

    MODE = "koikoi"
    TITLE = "こいこい"
    SEATS = 2
    FOLD_FEE = 1  # 文

    def __init__(self, months: int = 6, names: tuple[str, ...] = ("あなた", "CPU"),
                 rng: random.Random | None = None, dealer: int | None = None):
        super().__init__(months, names, rng, dealer)

    @property
    def opponent(self) -> Player:
        other = next(i for i in self.active if i != self.current)
        return self.players[other]

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
        month, deltas, active, folded, fee = self._new_result_args()
        if winner is None:
            self._log("流れ（引き分け）")
            self._record(KoikoiResult(month, deltas, active, folded, fee))
            return
        w = self.players[winner]
        yaku = find_yaku(w.captured)
        base = sum(y.points for y in yaku)
        points = final_score(base, self.opponent.koikoi if self.current == winner else False)
        deltas[winner] = points
        self.dealer = winner
        self._log(f"{w.name}: {points} 文獲得")
        self._record(KoikoiResult(month, deltas, active, folded, fee, winner, yaku, base, points))
