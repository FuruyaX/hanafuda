"""画面描画と操作（ブラウザ上の Pyodide で実行）。

ゲームの状態は持たず、protocol.view() が返す dict だけを描画する。
- オフライン / ホスト: この端末でゲームを進め（ホストは各ゲストに view を送る）
- ゲスト: ホストから届いた view を描画し、操作をホストへ送る
"""

from __future__ import annotations

import asyncio
import json

from js import document, window
from pyodide.ffi import create_once_callable, create_proxy

from hanafuda import ai, protocol
from hanafuda.cards import AME, CARDS_BY_ID, HOUOU, KIND_ORDER, MAKU, MONTH_FLOWERS, TSUKI, TSURU, Card, Kind
from hanafuda.game import MAX_PLAYERS, GameError, MatchingGame, Phase
from hanafuda.hanaawase import RULE_GUIDE, card_points, find_dekiyaku
from hanafuda.yaku import YAKU_GUIDE, base_score, find_yaku

KIND_CLASS = {Kind.HIKARI: "hikari", Kind.TANE: "tane", Kind.TAN: "tan", Kind.KASU: "kasu"}
CPU_DELAY_MS = 800
DEMO_DELAY_MS = 450
HOST = -1  # ゲスト側から見たホストの番号（net.js と同じ）
ACTING = {"declare", "play", "choose_hand", "choose_draw", "koikoi"}

MODES = {
    "koikoi": ("こいこい", "勝負は 2 人・役で勝負"),
    "hanaawase": ("花合わせ", "勝負は 3 人・札の点数と役"),
}


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def cards(ids) -> list[Card]:
    return [CARDS_BY_ID[i] for i in ids]


def card_html(c: Card, extra: str = "", action: str = "") -> str:
    attrs = f' data-action="{action}" data-id="{c.id}"' if action else ""
    ribbon = f'<span class="ribbon {c.ribbon}"></span>' if c.kind == Kind.TAN else ""
    label = "" if c.kind == Kind.KASU else f'<span class="label">{c.label}</span>'
    return (
        f'<div class="card m{c.month} {KIND_CLASS[c.kind]} {extra}"{attrs} title="{c.name}">'
        f'<span class="flower">{MONTH_FLOWERS[c.month - 1]}</span>{ribbon}{label}'
        f'<span class="month">{c.month}</span></div>'
    )


def back_html(extra: str = "") -> str:
    return f'<div class="card back {extra}"></div>'


def captured_html(mode: str, cs: list[Card]) -> str:
    groups = []
    for kind in KIND_ORDER:
        group = sorted((c for c in cs if c.kind == kind), key=lambda c: c.id)
        if group:
            inner = "".join(card_html(c, "mini") for c in group)
            groups.append(f'<div class="cap-group"><div class="cap-cards">{inner}</div>'
                          f'<span class="cap-count">{kind.value}{len(group)}</span></div>')
    if mode == "hanaawase":
        names = "・".join(y.name for y in find_dekiyaku(cs))
        tag = f'<div class="yaku-tag">{card_points(cs)}点{"　" + names if names else ""}</div>'
    else:
        yaku = find_yaku(cs)
        tag = f'<div class="yaku-tag">{"・".join(y.name for y in yaku)}（{sum(y.points for y in yaku)}文）</div>' \
            if yaku else ""
    return f'<div class="captured">{"".join(groups) or "<span class=empty>取り札なし</span>"}</div>{tag}'


def unit(mode: str) -> str:
    return "点" if mode == "hanaawase" else "文"


class App:
    def __init__(self) -> None:
        self.root = document.getElementById("app")
        self.screen = "title"  # title / yaku / lobby / join / game
        self.mode = "koikoi"
        self.months = 6
        self.count = 2  # 参加人数
        self.name = window.localStorage.getItem("hanafuda-name") or "あなた"
        self.role = "offline"  # offline / host / guest
        self.demo = False
        self.me = 0
        self.game: MatchingGame | None = None
        self.kinds: list[str] = []  # 席ごと: me / cpu / remote（オフライン・ホスト）
        self.view: dict | None = None
        self.selected: int | None = None
        self.notice = ""
        self.timer_gen = 0  # 画面を離れたら古いタイマーを無効にする
        self.lobby: dict[int, dict] = {}  # ホスト: 席 -> {status, code, name}
        self.join: dict = {}  # ゲスト: {reply, status, seat}
        self._click = create_proxy(self.on_click)
        self.root.addEventListener("click", self._click)
        window.net.onmessage = create_proxy(self.on_message)
        window.net.onstatus = create_proxy(self.on_status)

    # ================= 描画 =================
    def render(self) -> None:
        kept = {}  # 入力中の値は描き直しても残す
        for el in self.root.querySelectorAll("[data-keep]"):
            kept[el.id] = el.value
        html = {
            "title": self.title_html, "yaku": self.yaku_html, "lobby": self.lobby_html,
            "join": self.join_html, "game": self.game_html,
        }[self.screen]()
        self.root.innerHTML = html
        for key, value in kept.items():
            el = document.getElementById(key)
            if el:
                el.value = value

    def notice_html(self) -> str:
        return f'<p class="notice">{esc(self.notice)}</p>' if self.notice else ""

    def title_html(self) -> str:
        modes = "".join(
            f'<button class="chip mode {"on" if k == self.mode else ""}" data-action="mode" data-id="{k}">'
            f'{name}<small>{desc}</small></button>'
            for k, (name, desc) in MODES.items()
        )
        months = "".join(
            f'<button class="chip {"on" if m == self.months else ""}" data-action="months" data-id="{m}">{m}か月</button>'
            for m in (3, 6, 12)
        )
        seats = protocol.MODES[self.mode].SEATS
        self.count = max(self.count, seats)
        rule = ("参加者が " + str(seats) + " の倍数なら手札を見てから、そうでなければ手札なしで、"
                "親から順に勝負 / 降りを決めます") if self.count > seats else ""
        standalone = window.matchMedia("(display-mode: standalone)").matches
        install = ""
        if not standalone:
            if window.canInstall():
                install = '<button class="ghost" data-action="install">アプリとしてインストール</button>'
            elif window.isIOS():
                install = '<p class="hint">iPhone/iPad: 共有ボタン →「ホーム画面に追加」でアプリとして遊べます</p>'
        title_cards = "".join(card_html(c) for c in (TSURU, MAKU, TSUKI, AME, HOUOU))
        return f"""
        <div class="title">
          <h1>花札<span>{MODES[self.mode][0]}</span></h1>
          <div class="deco">{title_cards}</div>
          {self.notice_html()}
          <div class="chips">{modes}</div>
          <div class="chips">{months}</div>
          <div class="stepper">
            <button class="chip" data-action="count" data-id="-1">−</button>
            <span>参加 <b>{self.count}</b> 人</span>
            <button class="chip" data-action="count" data-id="1">＋</button>
          </div>
          <p class="hint">{rule}</p>
          <button class="primary" data-action="start">CPU と対戦</button>
          <div class="row2">
            <button data-action="host">部屋を作る（ホスト）</button>
            <button data-action="joinscreen">部屋に入る</button>
          </div>
          <button data-action="demo">デモ（CPU 同士の自動対戦）</button>
          <button data-action="yaku">役一覧</button>
          {install}
        </div>"""

    def yaku_html(self) -> str:
        koikoi = "".join(f"<tr><th>{n}</th><td>{p}文</td><td>{d}</td></tr>" for n, p, d in YAKU_GUIDE)
        hana = "".join(f"<tr><th>{n}</th><td>{p}</td><td>{d}</td></tr>" for n, p, d in RULE_GUIDE)
        return f"""
        <div class="page">
          <h2>こいこい（勝負 2 人）</h2>
          <table class="yaku-table">{koikoi}</table>
          <p class="hint">7 文以上は 2 倍。相手がこいこい中に上がるとさらに 2 倍。
            3 人以上では降りた人が勝負した 2 人に 1 文ずつ払う。</p>
          <h2>花合わせ（勝負 3 人）</h2>
          <table class="yaku-table">{hana}</table>
          <p class="hint">役の点は、持ち主が他の 2 人から 1 人分ずつ受け取ります。</p>
          <h2>人数が多いとき</h2>
          <p class="hint">参加は 12 人まで。毎月、親から順に「勝負 / 降り」を決め、席がうまったら残りは見学。
            残りの人数と空き席が同じになったら強制的に勝負。参加者が勝負人数の倍数なら手札を見てから決められます。</p>
          <button data-action="back">戻る</button>
        </div>"""

    # ---- オンライン: ホストの部屋 ----
    def lobby_html(self) -> str:
        rows = [f'<div class="seat"><b>席 1</b> {esc(self.name)}（ホスト・あなた）</div>']
        for seat in range(1, self.count):
            s = self.lobby[seat]
            if s["status"] == "connected":
                body = (f'<span class="ok">● {esc(s["name"])}（接続済み）</span>'
                        f'<button class="small" data-action="tocpu" data-id="{seat}">CPU に戻す</button>')
            elif s["status"] == "inviting":
                body = f"""
                  <div class="code-box">
                    <small>① この招待コードをゲストに送る</small>
                    <textarea readonly rows="3">{esc(s["code"])}</textarea>
                    <div class="row2">
                      <button class="small" data-action="copy" data-id="{seat}">コピー</button>
                      <button class="small" data-action="share" data-id="{seat}">共有</button>
                    </div>
                    <small>② ゲストから届いた返信コードを貼り付ける</small>
                    <textarea id="reply-{seat}" data-keep rows="3" placeholder="HF1.…"></textarea>
                    <div class="row2">
                      <button class="small primary" data-action="accept" data-id="{seat}">接続</button>
                      <button class="small" data-action="tocpu" data-id="{seat}">やめる</button>
                    </div>
                  </div>"""
            elif s["status"] == "working":
                body = "<span>コードを作成中…</span>"
            else:
                body = (f'<span>CPU</span>'
                        f'<button class="small" data-action="invite" data-id="{seat}">招待コードを作る</button>')
            rows.append(f'<div class="seat"><b>席 {seat + 1}</b> {body}</div>')
        return f"""
        <div class="page lobby">
          <h2>部屋（{MODES[self.mode][0]}・{self.count} 人・{self.months}か月）</h2>
          <p class="hint">同じ Wi-Fi の人を招待します。招待コードと返信コードを、LINE などで
            やり取りしてください（インターネットは不要。同じネットワーク内でつながります）。
            招待しない席は CPU が入ります。</p>
          {self.notice_html()}
          {"".join(rows)}
          <button class="primary" data-action="hoststart">対戦開始</button>
          <button data-action="title">部屋を閉じる</button>
        </div>"""

    # ---- オンライン: ゲストの参加 ----
    def join_html(self) -> str:
        j = self.join
        status = j.get("status", "")
        reply = ""
        if j.get("reply"):
            reply = f"""
              <div class="code-box">
                <small>② この返信コードをホストに送る（席 {j.get("seat", 0) + 1}）</small>
                <textarea readonly rows="3">{esc(j["reply"])}</textarea>
                <div class="row2">
                  <button class="small" data-action="copyreply">コピー</button>
                  <button class="small" data-action="sharereply">共有</button>
                </div>
              </div>"""
        return f"""
        <div class="page lobby">
          <h2>部屋に入る</h2>
          <label class="field-label">あなたの名前
            <input id="name" data-keep maxlength="10" value="{esc(self.name)}"></label>
          <small>① ホストから届いた招待コードを貼り付ける</small>
          <textarea id="invite" data-keep rows="3" placeholder="HF1.…"></textarea>
          <button class="primary" data-action="makereply">返信コードを作る</button>
          {reply}
          <p class="status">{esc(status)}</p>
          {self.notice_html()}
          <button data-action="title">やめる</button>
        </div>"""

    # ---- 対局 ----
    def game_html(self) -> str:
        v = self.view
        assert v is not None
        me = v["me"]
        mode = v["mode"]
        players = v["players"]
        phase = v["phase"]
        my_turn = v["current"] == me and not self.demo
        u = unit(mode)
        scores = " ／ ".join(f"{esc(p['name'])} {p['score']}{u}" for p in players) if len(players) <= 3 \
            else f"{esc(players[me]['name'])} {players[me]['score']}{u}（{len(players)} 人）"
        quit_label = "デモ終了" if self.demo else ("退出" if self.role == "guest" else "終了")
        header = f"""<header>
            <span>{v["title"]} {v["month"]}/{v["months"]}月 親:{esc(players[v["dealer"]]["name"])}</span>
            <span>{scores}</span>
            <button class="small" data-action="title">{quit_label}</button>
          </header>"""

        if phase == "declare":
            return f'<div class="board">{header}{self.bench_html()}{self.declare_html()}{self.notice_html()}</div>'

        me_active = players[me]["active"]
        playable = my_turn and phase == "play"
        field = cards(v["field"])
        hand = cards(v["hand"])
        targets: set[int] = set()
        if my_turn and phase in ("choose_hand", "choose_draw") and v["pending"] is not None:
            pending = CARDS_BY_ID[v["pending"]]
            targets = {c.id for c in field if c.month == pending.month}
        elif playable and self.selected is not None:
            sel = CARDS_BY_ID[self.selected]
            targets = {c.id for c in field if c.month == sel.month}

        field_html = "".join(
            card_html(c, "target" if c.id in targets else "", "field" if c.id in targets else "")
            for c in field
        )
        pending_html = ""
        if v["pending"] is not None:
            pending_html = (f'<div class="pending">{card_html(CARDS_BY_ID[v["pending"]], "glow")}'
                            f'<small>取る札を選択</small></div>')
        drawn = ""
        if v["last_drawn"] is not None and phase != "round_over":
            drawn = f'<div class="drawn"><small>めくった札</small>{card_html(CARDS_BY_ID[v["last_drawn"]], "mini")}</div>'

        # 自分が勝負していないとき（降り・見学）は、勝負している全員を上に並べる
        opp_idx = [i for i, p in enumerate(players) if p["active"] and i != me]
        opps = "".join(self.opponent_html(i) for i in opp_idx)
        if me_active:
            my_hand = "".join(
                card_html(c, "sel" if c.id == self.selected else "", "hand" if playable else "")
                for c in hand
            )
            mine = f"""<section class="side me">
                {captured_html(mode, cards(players[me]["captured"]))}
                <div class="who">{esc(players[me]["name"])}{self.marks(me)}</div>
                <div class="hand my-hand">{my_hand}</div>
              </section>"""
        else:
            state = "降り" if players[me]["folded"] else "見学"
            mine = f'<section class="side me"><div class="who">{esc(players[me]["name"])}（{state}中）</div></section>'

        return f"""
        <div class="board">
          {header}
          {self.bench_html()}
          <div class="opps n{len(opp_idx)}">{opps}</div>
          <section class="field-area">
            <div class="deck">{back_html()}<small>山 {v["deck_count"]}</small></div>
            <div class="field">{field_html}</div>
            {pending_html}{drawn}
          </section>
          <div class="message">{esc(self.message())}</div>
          {self.notice_html()}
          {mine}
          {self.modal_html()}
        </div>"""

    def bench_html(self) -> str:
        """勝負していない参加者（3 人目以降）の一覧。"""
        v = self.view
        players = v["players"]
        if len(players) <= v["seats"]:
            return ""
        u = unit(v["mode"])
        chips = []
        for i, p in enumerate(players):
            if v["phase"] == "declare":
                state = "勝負" if p["active"] else "降り" if p["folded"] else (
                    "考え中" if i == v["current"] else "")
            else:
                state = "勝負" if p["active"] else "降り" if p["folded"] else "見学"
            cls = "on" if p["active"] else "off" if state in ("降り", "見学") else ""
            me = "（あなた）" if i == v["me"] else ""
            chips.append(f'<span class="bench-chip {cls}">{esc(p["name"])}{me} {p["score"]}{u}'
                         f'{" ・" + state if state else ""}</span>')
        return f'<div class="bench">{"".join(chips)}</div>'

    def declare_html(self) -> str:
        v = self.view
        me = v["me"]
        players = v["players"]
        cur = players[v["current"]]
        fee = v["fold_fee"] * v["seats"]
        u = unit(v["mode"])
        if v["current"] == me and not self.demo:
            hand = "".join(card_html(c) for c in cards(v["hand"]))
            hand_html = f'<div class="hand my-hand">{hand}</div>' if hand else \
                '<p class="hint">今回は手札を見ずに決めます（参加人数が勝負人数の倍数でないため）</p>'
            return f"""<section class="declare">
                <h3>勝負しますか？</h3>
                {hand_html}
                <p class="hint">降りると、勝負した {v["seats"]} 人に降り賃 {v["fold_fee"]}{u} ずつ（計 {fee}{u}）払います</p>
                <div class="row2">
                  <button class="primary" data-action="declare" data-id="1">勝負</button>
                  <button data-action="declare" data-id="0">降りる</button>
                </div>
              </section>"""
        return f'<section class="declare"><p>{esc(cur["name"])} が勝負 / 降りを考えています…</p>' \
               f'<p class="hint">{esc(" / ".join(v["log"][-2:]))}</p></section>'

    def opponent_html(self, i: int) -> str:
        v = self.view
        p = v["players"][i]
        if "hand" in p:  # デモでは手札も見せる
            hand = "".join(card_html(c, "mini") for c in cards(p["hand"]))
        else:
            hand = "".join(back_html("mini") for _ in range(p["hand_count"]))
        return f"""<section class="side opp">
            <div class="who">{esc(p["name"])}{self.marks(i)}</div>
            <div class="hand small-hand">{hand}</div>
            {captured_html(v["mode"], cards(p["captured"]))}
          </section>"""

    def marks(self, i: int) -> str:
        v = self.view
        m = ""
        if v["current"] == i and v["phase"] in ACTING:
            m += ' <b class="turn">手番</b>'
        if v["players"][i]["koikoi"]:
            m += ' <b class="koi">こいこい中</b>'
        return m

    def message(self) -> str:
        v = self.view
        if self.demo or v["current"] != v["me"]:
            return v["log"][-1] if v["log"] else ""
        if v["phase"] == "play":
            return "手札を選んでください（もう一度タップ、または光った場札で出す）" if self.selected is None \
                else "同じ札をもう一度タップ、または光った場札をタップ"
        if v["phase"] in ("choose_hand", "choose_draw"):
            return "取る場札を選んでください"
        return v["log"][-1] if v["log"] else ""

    def modal_html(self) -> str:
        v = self.view
        me = v["me"]
        players = v["players"]
        u = unit(v["mode"])
        if v["phase"] == "koikoi" and v["current"] == me and not self.demo:
            mine = cards(players[me]["captured"])
            items = "".join(f"<li>{y.name} <b>{y.points}文</b></li>" for y in find_yaku(mine))
            return f"""<div class="modal"><div class="dialog">
              <h3>役ができました！</h3><ul>{items}</ul>
              <p>現在 {base_score(mine)} 文。勝負しますか？</p>
              <div class="row2">
                <button class="primary" data-action="decide" data-id="0">勝負</button>
                <button data-action="decide" data-id="1">こいこい</button>
              </div></div></div>"""
        if v["phase"] == "round_over" and v["result"]:
            r = v["result"]
            body = self.round_body(r)
            table = "".join(
                f"<tr><th>{esc(p['name'])}</th><td>{r['deltas'][i]:+d}</td><td>{p['score']}{u}</td></tr>"
                for i, p in enumerate(players)
            )
            last = v["month"] >= v["months"]
            if self.demo:
                btn = ""
            elif self.role == "guest":
                btn = '<p class="hint">ホストが次へ進めるのを待っています…</p>'
            else:
                btn = f'<button class="primary" data-action="next">{"結果を見る" if last else "次の月へ"}</button>'
            return f"""<div class="modal"><div class="dialog"><h3>{v["month"]}月目の結果</h3>{body}
              <table class="result-table"><tr><td></td><td>今月</td><td>合計</td></tr>{table}</table>
              {btn}</div></div>"""
        if v["phase"] == "game_over":
            w = v["winner"]
            head = "引き分け" if w is None else f"{esc(players[w]['name'])} の勝ち！"
            ranking = sorted(range(len(players)), key=lambda i: -players[i]["score"])
            rows = "".join(
                f"<tr><td>{rank + 1}位</td><th>{esc(players[i]['name'])}</th><td>{players[i]['score']}{u}</td></tr>"
                for rank, i in enumerate(ranking)
            )
            again = "" if self.role == "guest" else '<button class="primary" data-action="again">もう一度</button>'
            return f"""<div class="modal"><div class="dialog"><h3>{head}</h3>
              <table class="result-table">{rows}</table>
              <div class="row2">{again}<button data-action="title">タイトルへ</button></div></div></div>"""
        return ""

    def round_body(self, r: dict) -> str:
        players = self.view["players"]
        u = unit(self.view["mode"])
        fold = ""
        if r["folded"]:
            names = "・".join(esc(players[i]["name"]) for i in r["folded"])
            fold = f"<p class='hint'>降り賃: {names} が {r['fold_fee'] * len(r['active'])}{u} ずつ支払い</p>"
        if "tallies" in r:
            rows = ""
            for t in r["tallies"]:
                yaku = "・".join(f"{n}{p}" for n, p in t["dekiyaku"] + t["teyaku"]) or "-"
                rows += (f"<tr><th>{esc(players[t['seat']]['name'])}</th><td>{t['card_points']}</td>"
                         f"<td class='yk'>{yaku}</td><td><b>{t['delta']:+d}</b></td></tr>")
            return ("<table class='result-table tally'><tr><td></td><td>札点</td><td>役</td><td>増減</td></tr>"
                    f"{rows}</table><p class='hint'>札点は 88 を超えた分。役は他の 2 人から受け取る</p>{fold}")
        if r.get("winner") is None:
            return f"<p>流れ（引き分け）</p>{fold}"
        items = "".join(f"<li>{n} <b>{p}文</b></li>" for n, p in r["yaku"])
        bonus = " （倍付けあり）" if r["points"] != r["base"] else ""
        return (f"<p><b>{esc(players[r['winner']]['name'])}</b> の勝ち</p><ul>{items}</ul>"
                f"<p>{r['base']}文 → <b>{r['points']}文</b>{bonus}</p>{fold}")

    # ================= 進行（オフライン・ホスト） =================
    def start_game(self, names: list[str], kinds: list[str]) -> None:
        cls = protocol.MODES[self.mode]
        self.game = cls(months=self.months, names=tuple(names))
        self.kinds = kinds
        self.me = 0
        self.selected = None
        self.notice = ""
        self.screen = "game"
        self.timer_gen += 1
        self.after_change()

    def new_offline(self, demo: bool) -> None:
        self.closenet()
        self.role = "offline"
        self.demo = demo
        if demo:
            names = [f"CPU {chr(65 + i)}" for i in range(self.count)]
            kinds = ["cpu"] * self.count
        else:
            names = [self.name] + [f"CPU {i}" for i in range(1, self.count)]
            kinds = ["me"] + ["cpu"] * (self.count - 1)
        self.start_game(names, kinds)

    def after_change(self) -> None:
        """状態が変わるたびに描画し、ゲストに送り、CPU の番なら少し待って 1 手進める。"""
        g = self.game
        if g is None:
            return
        self.view = protocol.view(g, self.me, reveal_all=self.demo)
        if self.screen == "game":
            self.render()
        for seat, kind in enumerate(self.kinds):
            if kind == "remote":
                self.send(seat, {"kind": "view", "view": protocol.view(g, seat)})
        if g.phase == Phase.GAME_OVER:
            return
        if self.demo and g.phase == Phase.ROUND_OVER:
            self.schedule(3000)
        elif g.phase.value in ACTING and self.kinds[g.current] == "cpu":
            self.schedule(DEMO_DELAY_MS if self.demo else CPU_DELAY_MS)

    def schedule(self, ms: int) -> None:
        gen = self.timer_gen

        def step() -> None:
            if gen != self.timer_gen or self.game is None:
                return
            ai.act(self.game)
            self.after_change()

        window.setTimeout(create_once_callable(step), ms)

    def act(self, action: dict) -> None:
        """この端末のプレイヤーの操作。"""
        self.notice = ""
        if self.role == "guest":
            self.send(HOST, {"kind": "action", "action": action})
            return
        try:
            protocol.apply(self.game, self.me, action)
        except GameError as e:
            self.notice = str(e)
        self.after_change()

    # ================= 通信 =================
    def send(self, seat: int, msg: dict) -> None:
        window.net.send(seat, json.dumps(msg, ensure_ascii=False))

    def closenet(self) -> None:
        window.net.closeAll()
        self.lobby = {}
        self.join = {}

    def on_message(self, seat: int, text: str) -> None:
        msg = json.loads(text)
        kind = msg.get("kind")
        if self.role == "host":
            if kind == "hello" and seat in self.lobby:
                self.lobby[seat].update(status="connected", name=str(msg.get("name", "ゲスト"))[:10])
                if self.screen == "lobby":
                    self.render()
            elif kind == "action" and self.game is not None:
                try:
                    protocol.apply(self.game, seat, msg["action"])
                except GameError as e:
                    self.send(seat, {"kind": "error", "text": str(e)})
                    return
                self.after_change()
        elif self.role == "guest":
            if kind == "view":
                self.view = msg["view"]
                self.me = self.view["me"]
                if self.screen != "game":
                    self.screen = "game"
                    self.selected = None
                self.render()
            elif kind == "error":
                self.notice = msg.get("text", "")
                self.render()

    def on_status(self, seat: int, state: str) -> None:
        if self.role == "host" and seat in self.lobby:
            if state == "open":
                return  # 名前（hello）が届いたら接続済みにする
            if self.game is not None and self.screen == "game" and self.kinds[seat] == "remote":
                self.kinds[seat] = "cpu"  # 対局中に切れた席は CPU が引き継ぐ
                self.notice = f"席 {seat + 1} の接続が切れたので CPU が代わります"
                self.after_change()
            elif self.lobby[seat]["status"] == "connected":
                self.lobby[seat] = {"status": "cpu"}
                self.notice = f"席 {seat + 1} の接続が切れました"
                self.render()
        elif self.role == "guest" and seat == HOST:
            if state == "open":
                self.send(HOST, {"kind": "hello", "name": self.name})
                self.join["status"] = "接続しました。ホストが対戦を始めるのを待っています…"
                self.render()
            elif self.screen in ("game", "join"):
                self.notice = "ホストとの接続が切れました"
                self.render()

    async def make_invite(self, seat: int) -> None:
        self.lobby[seat] = {"status": "working"}
        self.render()
        try:
            code = await window.net.createInvite(seat)
            self.lobby[seat] = {"status": "inviting", "code": code}
        except Exception as e:  # noqa: BLE001
            self.lobby[seat] = {"status": "cpu"}
            self.notice = f"招待コードを作れませんでした: {e}"
        self.render()

    async def accept_reply(self, seat: int) -> None:
        el = document.getElementById(f"reply-{seat}")
        try:
            await window.net.acceptReply(seat, el.value if el else "")
            self.notice = f"席 {seat + 1}: 接続中…（つながると名前が表示されます）"
        except Exception as e:  # noqa: BLE001
            self.notice = f"席 {seat + 1}: {e}"
        self.render()

    async def make_reply(self) -> None:
        name_el = document.getElementById("name")
        if name_el and name_el.value.strip():
            self.name = name_el.value.strip()[:10]
            window.localStorage.setItem("hanafuda-name", self.name)
        invite = document.getElementById("invite").value
        self.join = {"status": "返信コードを作成中…"}
        self.notice = ""
        self.render()
        try:
            result = await window.net.acceptInvite(invite)
            self.join = {"reply": result.code, "seat": int(result.seat),
                         "status": "返信コードをホストに送ったら、つながるまで待ってください"}
        except Exception as e:  # noqa: BLE001
            self.join = {}
            self.notice = f"招待コードを読めませんでした: {e}"
        self.render()

    async def copy_text(self, text: str, share: bool) -> None:
        ok = await (window.net.share(text) if share else window.net.copy(text))
        if not ok and share:
            ok = await window.net.copy(text)
        self.notice = "コピーしました" if ok else "コピーできませんでした。コードを長押しして選択してください"
        self.render()

    # ================= 操作 =================
    def on_click(self, evt) -> None:
        el = evt.target.closest("[data-action]")
        if not el:
            return
        self.on_click_action(el.getAttribute("data-action"), el.getAttribute("data-id"))

    def on_click_action(self, action: str, raw: str | None = None) -> None:
        run = asyncio.ensure_future

        if action == "mode":
            self.mode = raw
            self.render()
        elif action == "months":
            self.months = int(raw)
            self.render()
        elif action == "count":
            seats = protocol.MODES[self.mode].SEATS
            self.count = min(MAX_PLAYERS, max(seats, self.count + int(raw)))
            self.render()
        elif action == "start":
            self.new_offline(demo=False)
        elif action == "demo":
            self.new_offline(demo=True)
        elif action == "yaku":
            self.screen = "yaku"
            self.render()
        elif action in ("back", "title"):
            self.timer_gen += 1
            self.closenet()
            self.game = None
            self.view = None
            self.role = "offline"
            self.screen = "title"
            self.render()
        elif action == "install":
            window.installApp()
        # ---- ホスト ----
        elif action == "host":
            self.closenet()
            self.role, self.demo, self.notice = "host", False, ""
            self.lobby = {seat: {"status": "cpu"} for seat in range(1, self.count)}
            self.screen = "lobby"
            self.render()
        elif action == "invite":
            self.notice = ""
            run(self.make_invite(int(raw)))
        elif action == "accept":
            run(self.accept_reply(int(raw)))
        elif action in ("copy", "share"):
            run(self.copy_text(self.lobby[int(raw)].get("code", ""), share=action == "share"))
        elif action == "tocpu":
            seat = int(raw)
            window.net.close(seat)
            self.lobby[seat] = {"status": "cpu"}
            self.render()
        elif action == "hoststart":
            names, kinds = [self.name], ["me"]
            for seat in range(1, self.count):
                s = self.lobby[seat]
                if s["status"] == "connected":
                    names.append(s["name"])
                    kinds.append("remote")
                else:
                    window.net.close(seat)  # 招待途中の席は CPU にする
                    names.append(f"CPU {seat}")
                    kinds.append("cpu")
            self.start_game(names, kinds)
        # ---- ゲスト ----
        elif action == "joinscreen":
            self.closenet()
            self.role, self.demo, self.notice = "guest", False, ""
            self.screen = "join"
            self.render()
        elif action == "makereply":
            run(self.make_reply())
        elif action in ("copyreply", "sharereply"):
            run(self.copy_text(self.join.get("reply", ""), share=action == "sharereply"))
        # ---- 対局 ----
        elif self.view is None:
            return
        elif action == "declare":
            self.act({"type": "declare", "play": raw == "1"})
        elif action == "hand":
            card_id = int(raw)
            if self.selected == card_id:
                self.selected = None
                self.act({"type": "play", "card": card_id})
            else:
                self.selected = card_id
                self.render()
        elif action == "field":
            card_id = int(raw)
            if self.view["phase"] == "play" and self.selected is not None:
                played = self.selected
                self.selected = None
                self.act({"type": "play", "card": played})
                # 候補が 2 枚だったときは、タップした場札を取る（オフライン・ホストは即座に判定できる）
                if self.role != "guest" and self.view["phase"] == "choose_hand":
                    self.act({"type": "choose", "card": card_id})
            else:
                self.act({"type": "choose", "card": card_id})
        elif action == "decide":
            self.act({"type": "decide", "koikoi": raw == "1"})
        elif action == "next":
            self.act({"type": "next"})
        elif action == "again":
            if self.game is not None:
                names = [p.name for p in self.game.players]
                self.start_game(names, self.kinds)


class LoopbackGuest:
    """自己診断（?loopback）用: 同じ画面の中のゲスト。ホストから届いた view だけを見て操作を返す。"""

    def __init__(self, app: App) -> None:
        self.app = app
        self.views = 0
        self.actions = 0

    def on_message(self, text: str) -> None:
        msg = json.loads(text)
        if msg.get("kind") != "view":
            return
        v = msg["view"]
        self.views += 1
        if v["current"] != v["me"] or v["phase"] not in ACTING:
            return
        field = cards(v["field"])
        if v["phase"] == "declare":
            action = {"type": "declare", "play": True}
        elif v["phase"] == "play":
            action = {"type": "play", "card": v["hand"][0]}
        elif v["phase"] in ("choose_hand", "choose_draw"):
            month = CARDS_BY_ID[v["pending"]].month
            action = {"type": "choose", "card": next(c.id for c in field if c.month == month)}
        else:
            action = {"type": "decide", "koikoi": False}
        self.actions += 1
        self.app.send(HOST, {"kind": "action", "action": action})


async def loopback_test(app: App) -> None:
    """ホストとして席 2 を招待し、同じ画面のゲストを WebRTC で参加させて対局を自動で進める。"""
    app.mode, app.months, app.count = "hanaawase", 2, 4
    app.role, app.screen = "host", "lobby"
    app.lobby = {seat: {"status": "cpu"} for seat in range(1, app.count)}
    bot = LoopbackGuest(app)
    original = app.on_message

    def route(seat: int, text: str) -> None:  # 席 -1 宛て（ゲスト側）はボットへ
        (bot.on_message(text) if seat == HOST else original(seat, text))

    window.net.onmessage = create_proxy(route)
    original_status = app.on_status

    def status(seat: int, state: str) -> None:
        if seat == HOST and state == "open":
            app.send(HOST, {"kind": "hello", "name": "ゲスト"})
        elif seat != HOST:
            original_status(seat, state)

    window.net.onstatus = create_proxy(status)
    await app.make_invite(1)
    reply = await window.net.acceptInvite(app.lobby[1]["code"])
    await window.net.acceptReply(1, reply.code)
    for _ in range(100):
        if app.lobby[1]["status"] == "connected":
            break
        await asyncio.sleep(0.1)
    app.on_click_action("hoststart")
    app.kinds[0] = "cpu"  # ホスト席も CPU にして自動で進める
    app.after_change()
    for _ in range(1500):
        if app.game.phase == Phase.GAME_OVER:
            break
        if app.game.phase == Phase.ROUND_OVER:
            app.act({"type": "next"})  # ホストとして次の月へ
        await asyncio.sleep(0.2)
    document.title = (f"LOOPBACK {'OK' if app.game.phase == Phase.GAME_OVER else 'NG'} "
                      f"views={bot.views} guest_actions={bot.actions} month={app.game.month} "
                      f"phase={app.game.phase.value} current={app.game.current} notice={app.notice}")


app: App | None = None


def start() -> None:
    global app
    app = App()
    params = window.location.search
    if "hanaawase" in params:  # ?demo&hanaawase で花合わせのデモ
        app.mode = "hanaawase"
    for part in params.lstrip("?").split("&"):
        if part.startswith("n="):  # ?demo&n=6 で参加人数
            app.count = int(part[2:])
    if "loopback" in params:  # 通信の自己診断
        asyncio.ensure_future(loopback_test(app))
        return
    if "demo" in params:  # ?demo 付きで開いたらデモを自動開始
        app.count = max(app.count, protocol.MODES[app.mode].SEATS)
        app.new_offline(demo=True)
    else:
        app.render()
