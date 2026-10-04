from collections import deque
from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import DataTable
from textual_plotext import PlotextPlot

from .feed import Tick

SPARK = "▁▂▃▄▅▆▇█"
SPARK_LEN = 20
FLASH_SECONDS = 0.5
UP, DOWN = "green", "red"


def fmt_price(value: float) -> str:
    return f"{value:,.2f}" if value >= 1_000 else f"{value:.4f}"


def change_arrow(pct: float) -> str:
    return "▲" if pct >= 0 else "▼"


def sparkline(values) -> str:
    lo, hi = min(values, default=0), max(values, default=0)
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
        self.update_cell(sym, "chg", Text(f"{change_arrow(pct)} {pct:+.2f}%", style=UP if pct >= 0 else DOWN))
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


class ChartPane(PlotextPlot):
    def on_mount(self):
        self.theme = "dark"
        self.show_message("select a pair")

    def show_message(self, text: str):
        self.plt.clear_data()
        self.plt.clear_figure()
        self.plt.title(text)
        self.refresh()

    def show(self, symbol: str, label: str, closes: list[tuple[float, float]]):
        if not closes:
            return self.show_message(f"{symbol} {label}: no data")
        # numeric x + our own tick labels: plotext's date parsing loses the day for "H:M" and wraps at midnight
        times = [t for t, _ in closes]
        fmt = "%d/%m" if label == "7d" else "%H:%M"
        ticks = times[:: max(1, len(times) // 5)]
        self.plt.clear_data()
        self.plt.clear_figure()
        self.plt.plot(times, [c for _, c in closes], color="orange", marker="braille")
        self.plt.xticks(ticks, [datetime.fromtimestamp(t, timezone.utc).strftime(fmt) for t in ticks])
        self.plt.title(f"{symbol} · {label} · close {fmt_price(closes[-1][1])} (UTC)")
        self.refresh()
