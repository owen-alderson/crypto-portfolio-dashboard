import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static

from .feed import Feed, Tick
from .history import TIMEFRAMES, fetch_closes, product_exists
from .widgets import ChartPane, PriceTable

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "crypto-terminal"
WATCHLIST_FILE = CONFIG_DIR / "watchlist.json"
DEFAULT_WATCHLIST = ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD", "ADA-USD"]
SYMBOL_RE = re.compile(r"[A-Z0-9]{1,10}-[A-Z0-9]{2,10}")
STALE_AFTER = 10  # seconds without any feed frame before the status line shows STALE


# ── Watchlist + commands ──────────────────────────────────────────────────────

def load_watchlist() -> list[str]:
    try:
        data = json.loads(WATCHLIST_FILE.read_text())
    except (OSError, ValueError):
        return list(DEFAULT_WATCHLIST)
    symbols = data.get("symbols") if isinstance(data, dict) else None
    if not isinstance(symbols, list):
        return list(DEFAULT_WATCHLIST)
    # file is user-editable: keep only well-formed pairs, drop duplicates
    return list(dict.fromkeys(s for s in symbols if isinstance(s, str) and SYMBOL_RE.fullmatch(s)))


def save_watchlist(symbols: list[str]):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps({"symbols": symbols}, indent=2))


def parse_command(text: str) -> tuple[str, str | None]:
    """`add SOL-USD` -> ("add", "SOL-USD"), `quit` -> ("quit", None). Raises ValueError with a user-facing message."""
    parts = text.split()
    if not parts:
        raise ValueError("empty command")
    cmd, args = parts[0].lower(), parts[1:]
    if cmd == "quit" and not args:
        return "quit", None
    if cmd in ("add", "rm"):
        if len(args) != 1:
            raise ValueError(f"usage: {cmd} BASE-QUOTE, e.g. {cmd} SOL-USD")
        symbol = args[0].upper()
        if not SYMBOL_RE.fullmatch(symbol):
            raise ValueError(f"not a pair: {args[0]} (expected e.g. SOL-USD)")
        return cmd, symbol
    raise ValueError(f"unknown command: {text.strip()} (try add / rm / quit)")


# ── App ───────────────────────────────────────────────────────────────────────

class TerminalApp(App):
    TITLE = "Crypto Terminal"
    CSS = """
    Screen { background: black; }
    #title { height: 1; padding: 0 1; background: #ffb000; color: black; text-style: bold; }
    #main { height: 1fr; }
    PriceTable { width: 62; height: 1fr; background: black; border-right: solid #ffb000; }
    PriceTable > .datatable--header { background: black; color: #ffb000; text-style: bold; }
    PriceTable > .datatable--cursor { background: #3a2a00; }
    #cmd { display: none; background: black; border: solid #ffb000; }
    #status { height: 1; padding: 0 1; background: #1c1c1c; color: #ffb000; }
    """
    BINDINGS = [
        ("slash", "command", "Command"),
        ("colon", "command", "Command"),
        ("escape", "close_command", "Close command bar"),
        ("1", "timeframe('1')", "1h"),
        ("2", "timeframe('2')", "1d"),
        ("3", "timeframe('3')", "7d"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("CRYPTO TERMINAL · COINBASE SPOT · [1] 1h [2] 1d [3] 7d · [/] command", id="title", markup=False)
        with Horizontal(id="main"):
            yield PriceTable(id="watchlist")
            yield ChartPane(id="chart")
        yield Input(placeholder="add SOL-USD · rm ADA-USD · quit   (esc to close)", id="cmd")
        yield Static(id="status", markup=False)  # status carries server text: never parse it as markup

    def on_mount(self):
        self.symbols = load_watchlist()
        self.http = httpx.AsyncClient()
        self.feed: Feed | None = None
        self.feed_status = "idle"
        self.last_tick = 0.0
        self.selected: str | None = None
        self.timeframe = "2"
        table = self.query_one(PriceTable)
        table.set_symbols(self.symbols)
        table.focus()
        self.restart_feed()
        self.set_interval(1, self.refresh_status)
        self.refresh_status()

    async def on_unmount(self):
        await self.http.aclose()

    # ── feed ──

    def restart_feed(self):
        if self.symbols:
            self.run_feed()  # exclusive worker: cancels the previous connection
        else:
            self.workers.cancel_group(self, "feed")
            self.feed = None
            self.handle_feed_status("idle")

    @work(exclusive=True, group="feed")
    async def run_feed(self):
        self.feed = Feed(self.symbols, self.handle_tick, self.handle_feed_status)
        await self.feed.run()

    def handle_tick(self, tick: Tick):
        self.last_tick = time.monotonic()
        self.query_one(PriceTable).update_tick(tick)

    def handle_feed_status(self, status: str):
        self.feed_status = status
        self.refresh_status()

    def refresh_status(self):
        now = time.monotonic()
        state = self.feed_status.upper()
        if self.feed and self.feed_status == "live" and now - self.feed.last_msg > STALE_AFTER:
            state = "STALE"
        age = f"{now - self.last_tick:.0f}s ago" if self.last_tick else "—"
        clock = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.query_one("#status", Static).update(f"● {state}  │  last tick {age}  │  {clock}")

    # ── chart ──

    def on_data_table_row_highlighted(self, event: PriceTable.RowHighlighted):
        self.selected = event.row_key.value
        self.load_chart()

    def action_timeframe(self, key: str):
        self.timeframe = key
        self.load_chart()

    @work(exclusive=True, group="chart")
    async def load_chart(self):
        # exclusive: a newer selection cancels this fetch, so a slow reply can't draw the wrong pair
        chart = self.query_one(ChartPane)
        if self.selected not in self.symbols:
            chart.show_message("watchlist empty: press / then `add BTC-USD`")
            return
        symbol, (label, span, granularity) = self.selected, TIMEFRAMES[self.timeframe]
        chart.show_message(f"loading {symbol} {label}…")
        try:
            closes = await fetch_closes(self.http, symbol, span, granularity)
        except httpx.HTTPError as e:
            chart.show_message(f"{symbol} {label}: history unavailable ({type(e).__name__})")
            return
        chart.show(symbol, label, closes)

    # ── command bar ──

    def action_command(self):
        cmd = self.query_one("#cmd", Input)
        cmd.display = True
        cmd.focus()

    def action_close_command(self):
        cmd = self.query_one("#cmd", Input)
        cmd.value, cmd.display = "", False
        self.query_one(PriceTable).focus()

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value
        self.action_close_command()
        try:
            cmd, symbol = parse_command(text)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        if cmd == "quit":
            self.exit()
        elif cmd == "add":
            self.add_symbol(symbol)
        elif symbol not in self.symbols:
            self.notify(f"{symbol} is not on the watchlist", severity="error")
        else:
            self.symbols.remove(symbol)
            self.watchlist_changed()

    @work(group="commands")
    async def add_symbol(self, symbol: str):
        if symbol in self.symbols:
            self.notify(f"{symbol} is already on the watchlist")
            return
        try:
            exists = await product_exists(self.http, symbol)
        except httpx.HTTPError as e:
            self.notify(f"could not check {symbol} with Coinbase ({type(e).__name__})", severity="error")
            return
        if not exists:
            self.notify(f"unknown pair: {symbol}", severity="error")
        elif symbol not in self.symbols:  # re-check: a second `add` may have landed while we awaited
            self.symbols.append(symbol)
            self.watchlist_changed()

    def watchlist_changed(self):
        save_watchlist(self.symbols)
        self.query_one(PriceTable).set_symbols(self.symbols)
        self.restart_feed()
        if not self.symbols:
            self.load_chart()
