"""画面とオンライン通信の共通の形。

- view(game, seat): その席から見える状態（他人の手札は枚数だけ）を JSON にできる dict で返す
- apply(game, seat, action): 席からの操作を検証して適用する
オフラインも、オンラインのホスト・ゲストも、画面はこの view だけを見て描画する。
"""

from __future__ import annotations

from typing import Any

from .game import Game, GameError, KoikoiResult, MatchingGame, Phase, RoundResult
from .hanaawase import HanaawaseGame, HanaawaseResult

HOST_SEAT = 0  # 月の進行（次の月へ）はホストが操作する

MODES: dict[str, type[MatchingGame]] = {"koikoi": Game, "hanaawase": HanaawaseGame}


def _yaku(ys) -> list[list[Any]]:
    return [[y.name, y.points] for y in ys]


def _result(r: RoundResult) -> dict[str, Any]:
    d: dict[str, Any] = {
        "month": r.month, "deltas": r.deltas, "active": r.active,
        "folded": r.folded, "fold_fee": r.fold_fee,
    }
    if isinstance(r, KoikoiResult):
        d.update(winner=r.winner, yaku=_yaku(r.yaku), base=r.base, points=r.points)
    if isinstance(r, HanaawaseResult):
        d["tallies"] = [
            {"seat": s, "card_points": t.card_points, "dekiyaku": _yaku(t.dekiyaku),
             "teyaku": _yaku(t.teyaku), "delta": t.delta}
            for s, t in zip(r.active, r.tallies)
        ]
    return d


def view(game: MatchingGame, seat: int, reveal_all: bool = False) -> dict[str, Any]:
    me = game.players[seat]
    players = []
    for i, p in enumerate(game.players):
        entry: dict[str, Any] = {
            "name": p.name, "score": p.score, "hand_count": len(p.hand),
            "captured": [c.id for c in p.captured], "active": i in game.active,
            "folded": p.folded, "koikoi": p.koikoi,
        }
        if reveal_all:
            entry["hand"] = [c.id for c in p.hand]
        players.append(entry)
    return {
        "mode": game.MODE, "title": game.TITLE, "seats": game.SEATS,
        "month": game.month, "months": game.months, "phase": game.phase.value,
        "current": game.current, "dealer": game.dealer, "me": seat,
        "sees_hand_on_declare": game.sees_hand_on_declare,
        "players": players, "hand": [c.id for c in me.hand],
        "field": [c.id for c in game.field], "deck_count": len(game.deck),
        "pending": game.pending.id if game.pending else None,
        "last_drawn": game.last_drawn.id if game.last_drawn else None,
        "log": game.log[-3:],
        "result": _result(game.last_result) if game.last_result else None,
        "results": [{"month": r.month, "deltas": r.deltas} for r in game.results],
        "winner": game.winner() if game.phase == Phase.GAME_OVER else None,
        "fold_fee": game.FOLD_FEE,
    }


def apply(game: MatchingGame, seat: int, action: dict[str, Any]) -> None:
    """席 seat からの操作。手番でない・不正な操作は GameError。"""
    kind = action.get("type")
    if kind == "next":
        if seat != HOST_SEAT:
            raise GameError("次の月へ進めるのはホストです")
        game.next_round()
        return
    if seat != game.current:
        raise GameError("手番ではありません")
    if kind == "declare":
        game.declare(bool(action["play"]))
    elif kind == "play":
        game.play(int(action["card"]))
    elif kind == "choose":
        game.choose(int(action["card"]))
    elif kind == "decide" and isinstance(game, Game):
        game.decide(bool(action["koikoi"]))
    else:
        raise GameError(f"不明な操作: {kind}")
