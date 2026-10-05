import time
from collections import deque

from rich.text import Text
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import DataTable, OptionList
from textual.widgets.option_list import Option

from . import chart
from .chart import fmt_price
from .feed import Tick
from .history import Candle, Product, apply_tick
from .indicators import ema, sma, vwap
from .theme import GREEN, RED

SPARK = "▁▂▃▄▅▆▇█"
SPARK_LEN = 20
FLASH_SECONDS = 0.5
UP, DOWN = GREEN, RED
REDRAW_EVERY = 0.25  # live candle redraws at most four times a second

# name -> (legend, colour, series over all candles); RSI gets its own panel
OVERLAYS = {
    "sma20": ("SMA 20", "yellow", lambda candles: sma([c.c for c in candles], 20)),
    "ema50": ("EMA 50", "cyan", lambda candles: ema([c.c for c in candles], 50)),
    "vwap": ("VWAP", "magenta", vwap),
}
INDICATORS = (*OVERLAYS, "rsi")


def sparkline(values) -> str:
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARK[0] * len(values)
    return "".join(SPARK[round((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in values)


class PriceTable(DataTable):
    """Watchlist: one row per pair, price flashes green/red on each up/down tick."""

    def on_mount(self):
        self.cursor_type = "row"
        for label, key, width in (("PAIR", "sym", 13), ("LAST", "last", 12), ("24H %", "chg", 10),
                                  ("TICKS", "spark", SPARK_LEN)):
            self.add_column(label, key=key, width=width)
        self._last: dict[str, Tick] = {}
        self._dir: dict[str, str] = {}
        self._spark: dict[str, deque] = {}
        self._flashing: set[str] = set()

    def set_symbols(self, symbols: list[str]):
        for sym in list(self._spark):
            if sym not in symbols:
                self.remove_row(sym)
                for d in (self._last, self._dir, self._spark):
                    d.pop(sym, None)
        for sym in symbols:
            if sym not in self._spark:
                self._spark[sym] = deque(maxlen=SPARK_LEN)
                self.add_row(Text(sym, style="bold"), "—", "—", "", key=sym)

    def set_alerts(self, symbols: set[str]):
        """Mark pairs that have an alert set."""
        for sym in self._spark:
            self.update_cell(sym, "sym", Text(f"{sym} 🔔" if sym in symbols else sym, style="bold"))

    def last_price(self, sym: str) -> float | None:
        return self._last[sym].price if sym in self._last else None

    def update_tick(self, tick: Tick):
        sym = tick.symbol
        if sym not in self._spark:  # late tick for a pair just removed
            return
        prev = self._last.get(sym)
        self._last[sym] = tick
        self._spark[sym].append(tick.price)
        if prev and tick.price != prev.price:
            self._dir[sym] = UP if tick.price > prev.price else DOWN
            if sym not in self._flashing:
                self._flashing.add(sym)
                self.set_timer(FLASH_SECONDS, lambda: self._unflash(sym))
        pct = (tick.price - tick.open_24h) / tick.open_24h * 100
        self.update_cell(sym, "chg", Text(f"{'▲' if pct >= 0 else '▼'} {pct:+.2f}%", style=UP if pct >= 0 else DOWN))
        self.update_cell(sym, "spark", Text(sparkline(self._spark[sym]), style="dark_orange"))
        self._render_price(sym)

    def _unflash(self, sym: str):
        self._flashing.discard(sym)
        if sym in self._last:
            self._render_price(sym)

    def _render_price(self, sym: str):
        color = self._dir.get(sym, "white")
        style = f"bold black on {color}" if sym in self._flashing else f"bold {color}"
        self.update_cell(sym, "last", Text(fmt_price(self._last[sym].price), style=style, justify="right"))


class PairPicker(ModalScreen[str | None]):
    """Search results for `add <coin>`: enter adds the highlighted pair, esc cancels."""

    BINDINGS = [("escape", "dismiss", "Cancel")]
    DEFAULT_CSS = """
    PairPicker { align: center middle; }
    PairPicker > OptionList { width: 50; height: auto; max-height: 20; background: black; border: solid #ffb000; }
    """

    def __init__(self, query: str, products: list[Product]):
        super().__init__()
        self.term, self.products = query, products

    def compose(self):
        # Text, not str: coin names are server data and must never be parsed as markup
        picker = OptionList(*(Option(Text(f"{p.id:<14}{p.name}"), id=p.id) for p in self.products))
        picker.border_title = f"add {self.term.lower()} · enter adds · esc cancels"
        yield picker

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(event.option.id)


class ChartPane(Widget):
    """Candles for one pair; the last candle follows live ticks via `update_price`."""

    DEFAULT_CSS = "ChartPane { width: 1fr; height: 1fr; }"

    def on_mount(self):
        self.symbol, self.candles, self.indicators, self._dirty, self.slot = None, [], set(), False, 2
        self.set_interval(REDRAW_EVERY, self._redraw_if_dirty)
        self.show_message("select a pair")

    def show_message(self, text: str):
        self.candles, self.message = [], text  # stop live updates until the next `show`
        self.refresh()

    def show(self, symbol: str, label: str, granularity: int, candles: list[Candle]):
        if not candles:
            return self.show_message(f"{symbol} {label}: no data")
        self.symbol, self.granularity, self.candles = symbol, granularity, candles
        self.refresh()

    def set_indicators(self, names):
        self.indicators = set(names)
        self._dirty = bool(self.candles)

    def update_price(self, symbol: str, price: float):
        if self.candles and symbol == self.symbol:
            apply_tick(self.candles, price, time.time(), self.granularity)
            self._dirty = True

    def _redraw_if_dirty(self):
        if self._dirty:
            self._dirty = False
            self.refresh()

    def render(self):
        if not self.candles:
            return Text(self.message)
        # indicators see the full history, not just the candles in view
        overlays = [(legend, colour, series(self.candles))
                    for name, (legend, colour, series) in OVERLAYS.items() if name in self.indicators]
        return Text("\n").join(chart.render(self.candles, self.granularity, self.size.width, self.size.height,
                                            self.slot, overlays, "rsi" in self.indicators))
