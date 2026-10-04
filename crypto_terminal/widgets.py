import math
import time
from collections import deque
from datetime import datetime, timezone

from rich.text import Text
from textual.screen import ModalScreen
from textual.widgets import DataTable, OptionList
from textual.widgets.option_list import Option
from textual_plotext import PlotextPlot

from .feed import Tick
from .history import Candle, Product, apply_tick
from .indicators import ema, rsi, sma, vwap

SPARK = "▁▂▃▄▅▆▇█"
SPARK_LEN = 20
SIG_FIGS = 5
FLASH_SECONDS = 0.5
UP, DOWN = "green", "red"
REDRAW_EVERY = 0.5  # live candle redraws at most twice a second
VOLUME_ROWS = 7
RSI_ROWS = 8

# name -> (legend, colour, series over all candles); RSI gets its own panel
OVERLAYS = {
    "sma20": ("SMA 20", "yellow", lambda candles: sma([c.c for c in candles], 20)),
    "ema50": ("EMA 50", "cyan", lambda candles: ema([c.c for c in candles], 50)),
    "vwap": ("VWAP", "magenta", vwap),
}
INDICATORS = (*OVERLAYS, "rsi")


def fmt_price(value: float) -> str:
    """2 decimals from 1,000 up, otherwise enough decimals for SIG_FIGS significant figures (0.0021300)."""
    if value >= 1_000:
        return f"{value:,.2f}"
    decimals = max(2, SIG_FIGS - 1 - math.floor(math.log10(value))) if value > 0 else 2
    return f"{value:.{decimals}f}"


def visible(times: list[float], series: list[float | None]) -> tuple[list, list]:
    """Tail of `series` lined up with `times`, minus the None warm-up."""
    pts = [(t, v) for t, v in zip(times, series[-len(times):]) if v is not None]
    return [t for t, _ in pts], [v for _, v in pts]


def sparkline(values) -> str:
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARK[0] * len(values)
    return "".join(SPARK[round((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in values)


class PriceTable(DataTable):
    """Watchlist: one row per pair, price flashes green/red on each up/down tick."""

    def on_mount(self):
        self.cursor_type = "row"
        for label, key, width in (("PAIR", "sym", 10), ("LAST", "last", 12), ("24H %", "chg", 10),
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


class ChartPane(PlotextPlot):
    """Candles for one pair; the last candle follows live ticks via `update_price`."""

    def on_mount(self):
        self.theme = "dark"
        self.symbol, self.candles, self.indicators, self._dirty = None, [], set(), False
        self.set_interval(REDRAW_EVERY, self._redraw_if_dirty)
        self.show_message("select a pair")

    def show_message(self, text: str):
        self.candles = []  # stop live updates until the next `show`
        self.plt.clear_figure()
        self.plt.title(text)
        self.refresh()

    def show(self, symbol: str, label: str, granularity: int, candles: list[Candle]):
        if not candles:
            return self.show_message(f"{symbol} {label}: no data")
        self.symbol, self.label, self.granularity, self.candles = symbol, label, granularity, candles
        self._draw()

    def set_indicators(self, names):
        self.indicators = set(names)
        self._dirty = bool(self.candles)

    def update_price(self, symbol: str, price: float):
        if self.candles and symbol == self.symbol:
            apply_tick(self.candles, price, time.time(), self.granularity)
            self._dirty = True

    def on_resize(self):
        self._dirty = bool(self.candles)  # visible candle count depends on width

    def _redraw_if_dirty(self):
        if self._dirty and self.candles:
            self._draw()

    def _draw(self):
        self._dirty = False
        # one terminal column per candle: draw the tail that fits; indicators see the full history
        shown = self.candles[-max(10, self.size.width - 12):]
        times = [c.t for c in shown]
        lines = [(legend, color, visible(times, series(self.candles)))
                 for name, (legend, color, series) in OVERLAYS.items() if name in self.indicators]
        show_rsi = "rsi" in self.indicators
        panels = 3 if show_rsi else 2
        plt = self.plt
        plt.clear_figure()
        plt.subplots(panels, 1)

        top = plt.subplot(1, 1)
        top.candlestick(times, {"Open": [c.o for c in shown], "Close": [c.c for c in shown],
                                "High": [c.h for c in shown], "Low": [c.l for c in shown]})
        for legend, color, (xs, ys) in lines:
            if xs:
                top.plot(xs, ys, color=color, marker="braille", label=legend)
        top.title(f"{self.symbol} · {self.label} · {fmt_price(shown[-1].c)} (UTC)")
        # our own y labels, padded to one width, so every panel's x axis lines up under the candles
        overlay_values = [y for _, _, (_, ys) in lines for y in ys]
        lo, hi = min([c.l for c in shown] + overlay_values), max([c.h for c in shown] + overlay_values)
        ys = [lo + (hi - lo) * i / 4 for i in range(5)]
        width = max(len(fmt_price(y)) for y in ys)
        top.yticks(ys, [fmt_price(y).rjust(width) for y in ys])

        vol = plt.subplot(2, 1)
        vol.plotsize(None, VOLUME_ROWS)
        vmax = max(c.v for c in shown)
        vol.bar(times, [c.v for c in shown], color="blue", width=0.5)
        vol.yticks([0, vmax], ["0".rjust(width), fmt_price(vmax).rjust(width)])

        if show_rsi:
            panel = plt.subplot(3, 1)
            panel.plotsize(None, RSI_ROWS)
            xs, ys = visible(times, rsi([c.c for c in self.candles]))
            if xs:
                panel.plot(xs, ys, color="orange", marker="braille", label="RSI 14")
            panel.hline(70, "gray")
            panel.hline(30, "gray")
            panel.ylim(0, 100)
            panel.yticks([30, 70], ["30".rjust(width), "70".rjust(width)])

        fmt = "%d/%m" if self.granularity >= 3600 else "%H:%M"
        ticks = times[:: max(1, len(times) // 5)]
        for row in range(1, panels + 1):
            panel = plt.subplot(row, 1)
            panel.xlim(times[0], times[-1])
            if row < panels:
                panel.xticks([])
        # numeric x + our own tick labels: plotext's date parsing loses the day for "H:M" and wraps at midnight
        panel.xticks(ticks, [datetime.fromtimestamp(t, timezone.utc).strftime(fmt) for t in ticks])
        self.refresh()
