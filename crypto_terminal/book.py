"""Order book and trade tape for one pair, from the same public feed (no API key).

`level2_batch` sends a full snapshot, then changes every 50 ms; `matches` sends every trade.
A malformed book message raises, so the feed reconnects and starts again from a fresh snapshot:
a book with a level silently missing would be wrong without looking wrong.
"""

import heapq
import math
import re
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable

from .feed import Feed

TAPE_LEN = 200
TIME_RE = re.compile(r"\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d)")


def decimals(text: str) -> int:
    return len(text.partition(".")[2])


def parse_number(text, allow_zero: bool = False) -> float:
    value = float(text)  # TypeError / ValueError for anything that isn't a number
    if not isinstance(text, str) or not (0 <= value < math.inf if allow_zero else 0 < value < math.inf):
        raise ValueError(f"bad number: {text!r}")
    return value


@dataclass(frozen=True)
class Trade:
    id: int
    time: str  # HH:MM:SS UTC
    price: float
    size: float
    buy: bool  # the taker bought (lifted the ask)
    dp: int  # decimals Coinbase quoted the price with
    missed: int = 0  # trades missing just before this one (trade ids are sequential per pair)


def parse_trade(msg: dict) -> Trade | None:
    """Validate a `match` / `last_match` message. Returns None for anything malformed."""
    if msg.get("type") not in ("match", "last_match"):
        return None
    try:
        trade_id, side, raw_price = msg["trade_id"], msg["side"], msg["price"]
        price, size = parse_number(raw_price), parse_number(msg["size"])
        clock = TIME_RE.match(msg["time"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(trade_id, int) or side not in ("buy", "sell") or not clock:
        return None
    # `side` is the resting (maker) order's side: a resting sell was hit by a buyer
    return Trade(trade_id, clock[1], price, size, side == "sell", decimals(raw_price))


class OrderBook:
    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.ready = False  # no snapshot yet: an empty book must never look like a real one
        self.dp = 0  # decimals Coinbase quotes prices with

    def load(self, msg: dict):
        """Replace the book with a `snapshot`. Raises ValueError if any level is malformed."""
        sides = []
        for key in ("bids", "asks"):
            if not isinstance(msg.get(key), list):
                raise ValueError(f"snapshot without {key}")
            levels = {}
            for row in msg[key]:
                try:
                    raw_price, raw_size = row
                    levels[parse_number(raw_price)] = parse_number(raw_size)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"malformed {key} level in snapshot: {row!r}") from e
                self.dp = max(self.dp, decimals(raw_price))
            sides.append(levels)
        self.bids, self.asks = sides
        self.ready = True

    def update(self, changes):
        """Apply an `l2update`'s changes; size 0 removes the level. Raises ValueError if any change is malformed."""
        if not isinstance(changes, list):
            raise ValueError("malformed l2update")
        parsed = []
        for row in changes:  # validate everything first, so a bad message changes nothing
            try:
                side, raw_price, raw_size = row
                parsed.append(({"buy": self.bids, "sell": self.asks}[side], parse_number(raw_price),
                               parse_number(raw_size, allow_zero=True)))
            except (TypeError, ValueError, KeyError) as e:
                raise ValueError(f"malformed l2update change: {row!r}") from e
            self.dp = max(self.dp, decimals(raw_price))
        for levels, price, size in parsed:
            if size:
                levels[price] = size
            else:
                levels.pop(price, None)

    def top(self, n: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Best `n` asks (lowest first) and best `n` bids (highest first) as (price, size)."""
        asks = [(p, self.asks[p]) for p in heapq.nsmallest(n, self.asks)]
        bids = [(p, self.bids[p]) for p in heapq.nlargest(n, self.bids)]
        return asks, bids


class BookFeed(Feed):
    """Order book + recent trades for one pair. `status` mirrors the connection; the book resets whenever it isn't
    live, so data from a dropped connection is never shown as current."""

    CHANNELS = ("level2_batch", "matches", "heartbeat")

    def __init__(self, symbol: str, on_status: Callable[[str], None] = lambda s: None, **kwargs):
        super().__init__([symbol], lambda tick: None, self._status, **kwargs)
        self.symbol, self.forward_status = symbol, on_status
        self.status = "idle"
        self.book = OrderBook()
        self.trades: deque[Trade] = deque(maxlen=TAPE_LEN)  # newest first

    def _status(self, status: str):
        if status != "live":
            self.book = OrderBook()
        self.status = status
        self.forward_status(status)

    def handle(self, msg: dict) -> bool:
        kind = msg.get("type")
        if msg.get("product_id") != self.symbol:
            return False
        if kind == "snapshot":
            self.book.load(msg)
        elif kind == "l2update":
            if self.book.ready:  # changes before the snapshot can't be applied to anything
                self.book.update(msg.get("changes"))
        elif kind in ("match", "last_match"):
            self.add_trade(parse_trade(msg))
        else:
            return False
        return True

    def add_trade(self, trade: Trade | None):
        if trade is None:  # malformed: the next trade's id shows it as missed
            return
        last = self.trades[0].id if self.trades else None
        if last is not None and trade.id <= last:  # `last_match` repeats a trade after a reconnect
            return
        if last is not None and trade.id > last + 1:
            trade = replace(trade, missed=trade.id - last - 1)
        self.trades.appendleft(trade)
