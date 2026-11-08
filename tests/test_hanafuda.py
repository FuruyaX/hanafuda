import random
from collections import Counter

import pytest

from hanafuda import ai
from hanafuda.cards import AME, DECK, MAKU, SAKAZUKI, TSUKI, TSURU, HOUOU, Kind, find
from hanafuda.game import Game, GameError, Phase
from hanafuda.yaku import base_score, final_score, find_yaku


def names(cards):
    return {y.name for y in find_yaku(cards)}


def test_deck_composition():
    assert len(DECK) == 48
    assert Counter(c.month for c in DECK) == {m: 4 for m in range(1, 13)}
    assert Counter(c.kind for c in DECK) == {Kind.HIKARI: 5, Kind.TANE: 9, Kind.TAN: 10, Kind.KASU: 24}


@pytest.mark.parametrize(
    "cards, expected",
    [
        ([TSURU, MAKU, TSUKI], "三光"),
        ([TSURU, MAKU, AME], None),  # 雨入りの 3 枚は役なし
        ([TSURU, MAKU, TSUKI, HOUOU], "四光"),
        ([TSURU, MAKU, TSUKI, AME], "雨四光"),
        ([TSURU, MAKU, TSUKI, AME, HOUOU], "五光"),
        ([find("猪", 7), find("鹿", 10), find("蝶", 6)], "猪鹿蝶"),
        ([MAKU, SAKAZUKI], "花見で一杯"),
        ([TSUKI, SAKAZUKI], "月見で一杯"),
        ([c for c in DECK if c.ribbon == "red"], "赤短"),
        ([c for c in DECK if c.ribbon == "blue"], "青短"),
    ],
)
def test_yaku(cards, expected):
    if expected is None:
        assert names(cards) == set()
    else:
        assert expected in names(cards)


def test_count_yaku():
    tan = [c for c in DECK if c.kind == Kind.TAN][:6]
    assert ("短冊", 2) in {(y.name, y.points) for y in find_yaku(tan)}
    kasu = [c for c in DECK if c.kind == Kind.KASU][:9]
    assert "カス" not in names(kasu)
    assert "カス" in names(kasu + [SAKAZUKI])  # 盃はカスにも数える


def test_final_score():
    assert final_score(5, False) == 5
    assert final_score(7, False) == 14
    assert final_score(3, True) == 6
    assert final_score(8, True) == 32


def test_invalid_operations():
    g = Game(rng=random.Random(1))
    other = g.opponent.hand[0]
    with pytest.raises(GameError):
        g.play(other.id)
    with pytest.raises(GameError):
        g.decide(True)


def _check_conservation(g: Game):
    zones = g.field + g.deck + ([g.pending] if g.pending else [])
    for p in g.players:
        zones += p.hand + p.captured
    assert sorted(c.id for c in zones) == list(range(48))


@pytest.mark.parametrize("seed", range(30))
def test_cpu_vs_cpu_full_game(seed):
    g = Game(months=12, rng=random.Random(seed))
    for _ in range(2000):
        if g.phase == Phase.GAME_OVER:
            break
        if g.phase != Phase.ROUND_OVER:
            _check_conservation(g)
        ai.act(g)
    assert g.phase == Phase.GAME_OVER
    assert len(g.results) == 12
    assert sum(r.points for r in g.results if r.winner == 0) == g.players[0].score
    assert sum(r.points for r in g.results if r.winner == 1) == g.players[1].score


def test_two_matches_requires_choice():
    g = Game(rng=random.Random(0))
    # 場に同じ月 2 枚、手札にその月 1 枚という状況を作る
    month_cards = [c for c in DECK if c.month == 1]
    p = g.player
    g.field = month_cards[:2]
    p.hand = [month_cards[2]]
    g.deck = [find("鳳凰", 12)]
    g.play(month_cards[2].id)
    assert g.phase == Phase.CHOOSE_HAND
    g.choose(month_cards[0].id)
    assert month_cards[0] in p.captured and month_cards[2] in p.captured
    assert month_cards[1] in g.field
    assert g.player is not p  # 手番が相手に移る


def test_round_ends_with_yaku_when_hand_empty():
    g = Game(rng=random.Random(0))
    p = g.player
    p.captured = [TSURU, MAKU]
    p.hand = [TSUKI]
    g.field = [c for c in DECK if c.month == 8 and c != TSUKI][:1]
    g.deck = [HOUOU]
    g.play(TSUKI.id)
    assert g.phase == Phase.ROUND_OVER
    assert g.last_result.winner == g.dealer
    assert base_score(p.captured) >= 5


# ---- 花合わせ ----
from hanafuda.hanaawase import (  # noqa: E402
    BASELINE, HanaawaseGame, card_points, find_dekiyaku, find_teyaku, settle,
)


def test_hanaawase_card_points_total():
    assert card_points(DECK) == 264
    assert BASELINE == 88


def test_hanaawase_dekiyaku():
    tan = [c for c in DECK if c.kind == Kind.TAN]
    assert {y.name for y in find_dekiyaku(tan[:6])} >= {"六短"}
    assert {y.name for y in find_dekiyaku(tan[:7])} >= {"七短"}
    assert "四光" in {y.name for y in find_dekiyaku([TSURU, MAKU, TSUKI, AME])}


def test_hanaawase_teyaku():
    kasu = [c for c in DECK if c.kind == Kind.KASU]
    assert [y.name for y in find_teyaku(kasu[:7])] == ["空素"]  # 1〜4 月のカス、3 枚そろう月なし
    three = [c for c in DECK if c.month == 2][:3]
    assert [y.name for y in find_teyaku(three + kasu[4:8])] == ["三本"]  # 2 月 3 枚 + 3・4 月のカス
    four = [c for c in DECK if c.month == 1]
    assert "手四" in {y.name for y in find_teyaku(four + kasu[8:11])}
    assert "光一" in {y.name for y in find_teyaku([HOUOU] + kasu[2:8])}


def test_settle_is_zero_sum():
    deltas = settle([100, 90, 74], [20, 0, 50])
    assert sum(deltas) == 0
    assert deltas[0] == (100 - 88) + 20 * 2 - 50


@pytest.mark.parametrize("seed", range(30))
def test_hanaawase_full_game(seed):
    g = HanaawaseGame(months=12, rng=random.Random(seed))
    assert len(g.deck) == 21 and all(len(p.hand) == 7 for p in g.players)
    for _ in range(3000):
        if g.phase == Phase.GAME_OVER:
            break
        if g.phase != Phase.ROUND_OVER:
            _check_conservation(g)
        ai.act(g)
    assert g.phase == Phase.GAME_OVER
    assert len(g.results) == 12
    assert sum(p.score for p in g.players) == 0
    for r in g.results:
        assert sum(t.card_points for t in r.tallies) == 264


# ---- 多人数（勝負 / 降り）とプロトコル ----
import json  # noqa: E402

from hanafuda import protocol  # noqa: E402
from hanafuda.game import MAX_PLAYERS  # noqa: E402


@pytest.mark.parametrize("mode", ["koikoi", "hanaawase"])
@pytest.mark.parametrize("n", range(2, MAX_PLAYERS + 1))
def test_many_players_full_game(mode, n):
    cls = protocol.MODES[mode]
    if n < cls.SEATS:
        with pytest.raises(ValueError):
            cls(names=tuple(f"P{i}" for i in range(n)))
        return
    for seed in range(3):
        g = cls(months=6, names=tuple(f"P{i}" for i in range(n)), rng=random.Random(seed * 100 + n))
        for _ in range(5000):
            if g.phase == Phase.GAME_OVER:
                break
            if g.phase not in (Phase.ROUND_OVER, Phase.DECLARE):
                _check_conservation(g)
                assert len(g.active) == cls.SEATS
                assert all(not p.hand for i, p in enumerate(g.players) if i not in g.active)
            # 手札を見て決めるのは参加者数が席数の倍数のときだけ
            if g.phase == Phase.DECLARE:
                assert bool(g.player.hand) == (n % cls.SEATS == 0)
            json.dumps(protocol.view(g, 0))  # どの局面でも JSON にできる
            ai.act(g)
        assert g.phase == Phase.GAME_OVER
        for r in g.results:
            assert len(r.deltas) == n
            assert set(r.folded).isdisjoint(r.active)
            if mode == "hanaawase":
                assert sum(r.deltas) == 0  # 降り賃を含めても合計 0


def test_fold_fee_and_forced_play():
    # 4 人の花合わせ: 親から 3 人が降りることはできない（残り 3 人なら強制）
    g = HanaawaseGame(months=1, names=("A", "B", "C", "D"), rng=random.Random(5), dealer=0)
    assert g.phase == Phase.DECLARE and g.current == 0
    assert g.player.hand == []  # 4 人は 3 の倍数でないので手札なし
    g.declare(False)  # A が降りる → 残り 3 人は強制的に勝負
    assert g.phase == Phase.PLAY
    assert g.active == [1, 2, 3]
    while g.phase != Phase.ROUND_OVER:
        ai.act(g)
    r = g.last_result
    assert r.folded == [0]
    assert r.deltas[0] == -5 * 3


def test_sees_hand_when_multiple_of_seats():
    g = Game(months=1, names=("A", "B", "C", "D"), rng=random.Random(1), dealer=0)
    assert g.sees_hand_on_declare and len(g.player.hand) == 8
    shown = list(g.player.hand)
    g.declare(False)
    assert g.players[0].hand == []
    assert all(c in g.deck or c in g.player.hand for c in shown)  # 山に戻った


def test_protocol_hides_other_hands_and_checks_turn():
    g = Game(rng=random.Random(3))
    v = protocol.view(g, 0)
    assert v["hand"] == [c.id for c in g.players[0].hand]
    assert "hand" not in v["players"][1] and v["players"][1]["hand_count"] == 8
    other = 1 - g.current
    with pytest.raises(GameError):
        protocol.apply(g, other, {"type": "play", "card": g.players[other].hand[0].id})
    protocol.apply(g, g.current, {"type": "play", "card": g.player.hand[0].id})
