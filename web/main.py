"""画面描画と操作（ブラウザ上の Pyodide で実行）。ロジックは hanafuda パッケージに任せる。"""

from __future__ import annotations

from js import document, window
from pyodide.ffi import create_once_callable, create_proxy

from hanafuda import ai
from hanafuda.cards import AME, HOUOU, KIND_ORDER, MAKU, MONTH_FLOWERS, TSUKI, TSURU, Card, Kind
from hanafuda.game import Game, KoikoiResult, MatchingGame, Phase
from hanafuda.hanaawase import RULE_GUIDE, HanaawaseGame, HanaawaseResult, card_points, find_dekiyaku
from hanafuda.yaku import YAKU_GUIDE, base_score, find_yaku

HUMAN = 0
KIND_CLASS = {Kind.HIKARI: "hikari", Kind.TANE: "tane", Kind.TAN: "tan", Kind.KASU: "kasu"}
CPU_DELAY_MS = 800
DEMO_DELAY_MS = 450

MODES = {
    "koikoi": ("こいこい", "2 人・役で勝負"),
    "hanaawase": ("花合わせ", "3 人・札の点数と役"),
}


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


def captured_html(game: MatchingGame, cards: list[Card]) -> str:
    groups = []
    for kind in KIND_ORDER:
        cs = sorted((c for c in cards if c.kind == kind), key=lambda c: c.id)
        if cs:
            inner = "".join(card_html(c, "mini") for c in cs)
            groups.append(f'<div class="cap-group"><div class="cap-cards">{inner}</div>'
                          f'<span class="cap-count">{kind.value}{len(cs)}</span></div>')
    if isinstance(game, HanaawaseGame):
        yaku = find_dekiyaku(cards)
        names = "・".join(y.name for y in yaku)
        tag = f'<div class="yaku-tag">{card_points(cards)}点{"　" + names if names else ""}</div>'
    else:
        yaku = find_yaku(cards)
        tag = f'<div class="yaku-tag">{"・".join(y.name for y in yaku)}（{sum(y.points for y in yaku)}文）</div>' \
            if yaku else ""
    return f'<div class="captured">{"".join(groups) or "<span class=empty>取り札なし</span>"}</div>{tag}'


def unit(game: MatchingGame) -> str:
    return "点" if isinstance(game, HanaawaseGame) else "文"


class App:
    def __init__(self) -> None:
        self.root = document.getElementById("app")
        self.screen = "title"  # title / game / yaku
        self.mode = "koikoi"
        self.months = 6
        self.game: MatchingGame | None = None
        self.demo = False
        self.selected: int | None = None
        self.timer_gen = 0  # 画面を離れたら古いタイマーを無効にする
        self._click = create_proxy(self.on_click)
        self.root.addEventListener("click", self._click)

    # ---- 画面 ----
    def render(self) -> None:
        if self.screen == "title":
            self.root.innerHTML = self.title_html()
        elif self.screen == "yaku":
            self.root.innerHTML = self.yaku_html()
        else:
            self.root.innerHTML = self.game_html()

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
        standalone = window.matchMedia("(display-mode: standalone)").matches
        install = ""
        if not standalone:
            if window.canInstall():
                install = '<button class="ghost" data-action="install">アプリとしてインストール</button>'
            elif window.isIOS():
                install = '<p class="hint">iPhone/iPad: 共有ボタン →「ホーム画面に追加」でアプリとして遊べます</p>'
            else:
                install = '<p class="hint">ブラウザのメニューから「ホーム画面に追加 / アプリをインストール」</p>'
        title_cards = "".join(card_html(c) for c in (TSURU, MAKU, TSUKI, AME, HOUOU))
        return f"""
        <div class="title">
          <h1>花札<span>{MODES[self.mode][0]}</span></h1>
          <div class="deco">{title_cards}</div>
          <div class="chips">{modes}</div>
          <div class="chips">{months}</div>
          <button class="primary" data-action="start">対戦開始</button>
          <button data-action="demo">デモ（CPU 同士の自動対戦）</button>
          <button data-action="yaku">役一覧</button>
          {install}
        </div>"""

    def yaku_html(self) -> str:
        koikoi = "".join(f"<tr><th>{n}</th><td>{p}文</td><td>{d}</td></tr>" for n, p, d in YAKU_GUIDE)
        hana = "".join(f"<tr><th>{n}</th><td>{p}</td><td>{d}</td></tr>" for n, p, d in RULE_GUIDE)
        return f"""
        <div class="page">
          <h2>こいこい</h2>
          <table class="yaku-table">{koikoi}</table>
          <p class="hint">7 文以上は 2 倍。相手がこいこい中に上がるとさらに 2 倍。</p>
          <h2>花合わせ（3 人）</h2>
          <table class="yaku-table">{hana}</table>
          <p class="hint">役の点は、持ち主が他の 2 人から 1 人分ずつ受け取ります。</p>
          <button data-action="back">戻る</button>
        </div>"""

    def opponent_html(self, i: int) -> str:
        g = self.game
        assert g is not None
        p = g.players[i]
        hand = "".join(card_html(c, "mini") for c in p.hand) if self.demo \
            else "".join(back_html("mini") for _ in p.hand)  # デモでは手札も見せる
        return f"""<section class="side opp">
            <div class="who">{p.name}{self.marks(i)}</div>
            <div class="hand small-hand">{hand}</div>
            {captured_html(g, p.captured)}
          </section>"""

    def marks(self, i: int) -> str:
        g = self.game
        assert g is not None
        m = ""
        if g.current == i and g.phase not in (Phase.ROUND_OVER, Phase.GAME_OVER):
            m += ' <b class="turn">手番</b>'
        if g.players[i].koikoi:
            m += ' <b class="koi">こいこい中</b>'
        return m

    def game_html(self) -> str:
        g = self.game
        assert g is not None
        you = g.players[HUMAN]
        human_turn = not self.demo and g.current == HUMAN
        playable = human_turn and g.phase == Phase.PLAY

        # 光らせる場札（選択中の手札の相手 / 選択待ちの候補）
        targets: set[int] = set()
        if human_turn and g.phase in (Phase.CHOOSE_HAND, Phase.CHOOSE_DRAW) and g.pending:
            targets = {c.id for c in g.matches(g.pending)}
        elif playable and self.selected is not None:
            sel = next((c for c in you.hand if c.id == self.selected), None)
            if sel:
                targets = {c.id for c in g.matches(sel)}

        field = "".join(
            card_html(c, "target" if c.id in targets else "", "field" if c.id in targets else "")
            for c in g.field
        )
        pending = ""
        if g.pending:
            pending = f'<div class="pending">{card_html(g.pending, "glow")}<small>取る札を選択</small></div>'
        drawn = ""
        if g.last_drawn and g.phase != Phase.ROUND_OVER:
            drawn = f'<div class="drawn"><small>めくった札</small>{card_html(g.last_drawn, "mini")}</div>'

        my_hand = "".join(
            card_html(c, "sel" if c.id == self.selected else "", "hand" if playable else "")
            for c in you.hand
        )
        scores = " ／ ".join(f"{p.name} {p.score}{unit(g)}" for p in g.players)
        opps = "".join(self.opponent_html(i) for i in range(1, len(g.players)))
        quit_label = "デモ終了" if self.demo else "終了"

        return f"""
        <div class="board">
          <header>
            <span>{g.TITLE} {g.month}/{g.months}月 親:{g.players[g.dealer].name}</span>
            <span>{scores}</span>
            <button class="small" data-action="title">{quit_label}</button>
          </header>
          <div class="opps n{len(g.players) - 1}">{opps}</div>
          <section class="field-area">
            <div class="deck">{back_html()}<small>山 {len(g.deck)}</small></div>
            <div class="field">{field}</div>
            {pending}{drawn}
          </section>
          <div class="message">{self.message()}</div>
          <section class="side me">
            {captured_html(g, you.captured)}
            <div class="who">{you.name}{self.marks(HUMAN)}</div>
            <div class="hand my-hand">{my_hand}</div>
          </section>
          {self.modal_html()}
        </div>"""

    def message(self) -> str:
        g = self.game
        assert g is not None
        if self.demo or g.current != HUMAN:
            return g.log[-1] if g.log else ""
        if g.phase == Phase.PLAY:
            return "手札を選んでください（もう一度タップ、または光った場札で出す）" if self.selected is None \
                else "同じ札をもう一度タップ、または光った場札をタップ"
        if g.phase in (Phase.CHOOSE_HAND, Phase.CHOOSE_DRAW):
            return "取る場札を選んでください"
        return g.log[-1] if g.log else ""

    def modal_html(self) -> str:
        g = self.game
        assert g is not None
        if g.phase == Phase.KOIKOI and g.current == HUMAN and not self.demo:
            yaku = find_yaku(g.player.captured)
            items = "".join(f"<li>{y.name} <b>{y.points}文</b></li>" for y in yaku)
            return f"""<div class="modal"><div class="dialog">
              <h3>役ができました！</h3><ul>{items}</ul>
              <p>現在 {base_score(g.player.captured)} 文。勝負しますか？</p>
              <div class="row">
                <button class="primary" data-action="stop">勝負</button>
                <button data-action="koikoi">こいこい</button>
              </div></div></div>"""
        totals = " ／ ".join(f"{p.name} {p.score}{unit(g)}" for p in g.players)
        if g.phase == Phase.ROUND_OVER and g.last_result:
            body = self.round_body(g.last_result)
            label = "結果を見る" if g.month >= g.months else "次の月へ"
            btn = "" if self.demo else f'<button class="primary" data-action="next">{label}</button>'
            return f"""<div class="modal"><div class="dialog"><h3>{g.month}月目の結果</h3>{body}
              <p>合計: {totals}</p>{btn}</div></div>"""
        if g.phase == Phase.GAME_OVER:
            w = g.winner()
            head = "引き分け" if w is None else f"{g.players[w].name} の勝ち！"
            th = "".join(f"<th>{p.name}</th>" for p in g.players)
            rows = "".join(
                f"<tr><td>{r.month}月</td>{''.join(f'<td>{d:+d}</td>' for d in r.deltas)}</tr>"
                for r in g.results
            )
            return f"""<div class="modal"><div class="dialog"><h3>{head}</h3>
              <p>{totals}</p>
              <table class="result-table"><tr><td></td>{th}</tr>{rows}</table>
              <div class="row"><button class="primary" data-action="again">もう一度</button>
              <button data-action="title">タイトルへ</button></div></div></div>"""
        return ""

    def round_body(self, r) -> str:
        g = self.game
        assert g is not None
        if isinstance(r, HanaawaseResult):
            rows = ""
            for p, t in zip(g.players, r.tallies):
                yaku = "・".join(f"{y.name}{y.points}" for y in t.dekiyaku + t.teyaku) or "-"
                rows += (f"<tr><th>{p.name}</th><td>{t.card_points}</td>"
                         f"<td class='yk'>{yaku}</td><td><b>{t.delta:+d}</b></td></tr>")
            return ("<table class='result-table tally'><tr><td></td><td>札点</td><td>役</td><td>増減</td></tr>"
                    f"{rows}</table><p class='hint'>札点は 88 を超えた分。役は他の 2 人から受け取る</p>")
        assert isinstance(r, KoikoiResult)
        if r.winner is None:
            return "<p>流れ（引き分け）</p>"
        items = "".join(f"<li>{y.name} <b>{y.points}文</b></li>" for y in r.yaku)
        bonus = " （倍付けあり）" if r.points != r.base else ""
        return (f"<p><b>{g.players[r.winner].name}</b> の勝ち</p><ul>{items}</ul>"
                f"<p>{r.base}文 → <b>{r.points}文</b>{bonus}</p>")

    # ---- 進行 ----
    def new_game(self, demo: bool) -> None:
        self.demo = demo
        if self.mode == "hanaawase":
            names = ("CPU A", "CPU B", "CPU C") if demo else ("あなた", "CPU 1", "CPU 2")
            self.game = HanaawaseGame(months=self.months, names=names)
        else:
            names = ("CPU 先手", "CPU 後手") if demo else ("あなた", "CPU")
            self.game = Game(months=self.months, names=names)
        self.selected = None
        self.screen = "game"
        self.timer_gen += 1
        self.after_change()

    def after_change(self) -> None:
        """状態が変わるたびに描画し、CPU の番なら少し待って 1 手進める。"""
        self.render()
        g = self.game
        if self.screen != "game" or g is None or g.phase == Phase.GAME_OVER:
            return
        cpu_turn = g.current != HUMAN and g.phase in (
            Phase.PLAY, Phase.CHOOSE_HAND, Phase.CHOOSE_DRAW, Phase.KOIKOI)
        if self.demo:
            delay = 3000 if g.phase == Phase.ROUND_OVER else DEMO_DELAY_MS
            self.schedule(delay)
        elif cpu_turn:
            self.schedule(CPU_DELAY_MS)

    def schedule(self, ms: int) -> None:
        gen = self.timer_gen

        def step() -> None:
            if gen != self.timer_gen or self.game is None:
                return
            ai.act(self.game)
            self.after_change()

        window.setTimeout(create_once_callable(step), ms)

    # ---- 操作 ----
    def on_click(self, evt) -> None:
        el = evt.target.closest("[data-action]")
        if not el:
            return
        action = el.getAttribute("data-action")
        raw_id = el.getAttribute("data-id")
        g = self.game

        if action == "mode":
            self.mode = raw_id
            self.render()
        elif action == "months":
            self.months = int(raw_id)
            self.render()
        elif action == "start":
            self.new_game(demo=False)
        elif action == "demo":
            self.new_game(demo=True)
        elif action == "yaku":
            self.screen = "yaku"
            self.render()
        elif action in ("back", "title"):
            self.timer_gen += 1
            self.screen = "title"
            self.render()
        elif action == "install":
            window.installApp()
        elif g is None:
            return
        elif action == "hand":
            card_id = int(raw_id)
            if self.selected == card_id:
                self.selected = None
                g.play(card_id)
                self.after_change()
            else:
                self.selected = card_id
                self.render()
        elif action == "field":
            card_id = int(raw_id)
            if g.phase == Phase.PLAY and self.selected is not None:
                card = self.selected
                self.selected = None
                g.play(card)
                if g.phase == Phase.CHOOSE_HAND:  # 候補 2 枚なら、タップした札を取る
                    g.choose(card_id)
            else:
                g.choose(card_id)
            self.after_change()
        elif action == "stop" and isinstance(g, Game):
            g.decide(False)
            self.after_change()
        elif action == "koikoi" and isinstance(g, Game):
            g.decide(True)
            self.after_change()
        elif action == "next":
            g.next_round()
            self.after_change()
        elif action == "again":
            self.new_game(demo=self.demo)


app: App | None = None


def start() -> None:
    global app
    app = App()
    params = window.location.search
    if "hanaawase" in params:  # ?demo&hanaawase で花合わせのデモ
        app.mode = "hanaawase"
    if "demo" in params:  # ?demo 付きで開いたらデモを自動開始
        app.new_game(demo=True)
    else:
        app.render()
