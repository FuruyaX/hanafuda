"""CPU の思考。札の価値と役への近さで貪欲に選ぶ（こいこい・花合わせ共通）。"""

from __future__ import annotations

from .cards import AKATAN, AOTAN, CHOU, INO, SAKAZUKI, SHIKA, Card, Kind
from .game import Game, MatchingGame, Phase
from .hanaawase import CARD_POINTS, HanaawaseGame, find_dekiyaku
from .yaku import base_score

_KIND_VALUE = {Kind.HIKARI: 10, Kind.TANE: 5, Kind.TAN: 4, Kind.KASU: 1}
_YAKU_PARTS = {INO, SHIKA, CHOU, SAKAZUKI} | AKATAN | AOTAN


def card_value(game: MatchingGame, card: Card) -> float:
    if isinstance(game, HanaawaseGame):
        return CARD_POINTS[card.kind] + (6 if card in _YAKU_PARTS else 0)
    return _KIND_VALUE[card.kind] + (3 if card in _YAKU_PARTS else 0)


def _gain(game: MatchingGame, captured: list[Card], new: list[Card]) -> float:
    """札を取ったときの評価: 札の価値 + 役の点の増加。"""
    value = sum(card_value(game, c) for c in new)
    if isinstance(game, HanaawaseGame):
        before = sum(y.points for y in find_dekiyaku(captured))
        after = sum(y.points for y in find_dekiyaku(captured + new))
        return value + (after - before) * 2  # 役は他の 2 人から受け取る
    return value + (base_score(captured + new) - base_score(captured)) * 15


def _best_match(game: MatchingGame, card: Card) -> Card:
    return max(game.matches(card), key=lambda c: card_value(game, c))


def choose_play(game: MatchingGame) -> Card:
    p = game.player
    best: tuple[float, Card] | None = None
    for card in p.hand:
        m = game.matches(card)
        if not m:
            score = -card_value(game, card)  # 場に捨てると相手に取られうる
        elif len(m) == 2:
            score = _gain(game, p.captured, [card, _best_match(game, card)])
        else:
            score = _gain(game, p.captured, [card, *m])
        score += game.rng.random() * 0.5  # 同点のときのばらつき
        if best is None or score > best[0]:
            best = (score, card)
    assert best is not None
    return best[1]


def decide_koikoi(game: Game) -> bool:
    """True ならこいこい。点が低く、手札に余裕があり、相手が役に遠いときだけ続ける。"""
    p, opp = game.player, game.opponent
    base = base_score(p.captured)
    opp_lights = sum(1 for c in opp.captured if c.kind == Kind.HIKARI)
    opp_tan = sum(1 for c in opp.captured if c.kind == Kind.TAN)
    opp_tane = sum(1 for c in opp.captured if c.kind == Kind.TANE)
    opp_close = opp_lights >= 2 or opp_tan >= 4 or opp_tane >= 4
    return base < 5 and len(p.hand) >= 4 and not opp_close


def act(game: MatchingGame) -> None:
    """現在の手番プレイヤーとして 1 手進める（CPU とデモ用）。"""
    if game.phase == Phase.PLAY:
        game.play(choose_play(game).id)
    elif game.phase in (Phase.CHOOSE_HAND, Phase.CHOOSE_DRAW):
        assert game.pending is not None
        game.choose(_best_match(game, game.pending).id)
    elif game.phase == Phase.KOIKOI:
        assert isinstance(game, Game)
        game.decide(decide_koikoi(game))
    elif game.phase == Phase.ROUND_OVER:
        game.next_round()
