"""Coinbase Exchange public websocket feed (ticker + heartbeat channels, no API key)."""

import asyncio
import json
import math
import random
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import certifi
from websockets.asyncio.client import connect

FEED_URL = "wss://ws-feed.exchange.coinbase.com"
RECONNECT_AFTER = 30  # seconds of silence (heartbeats arrive every 1s) before the socket is presumed dead
MAX_BACKOFF = 30

# python.org macOS builds ship without a CA bundle; use certifi's so wss:// works everywhere
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    open_24h: float
    ts: float  # exchange time, unix seconds


def parse_message(raw) -> dict | None:
    """Decode a feed frame; anything that isn't a JSON object is dropped."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return msg if isinstance(msg, dict) else None


def parse_tick(msg: dict) -> Tick | None:
    """Validate a `ticker` message. Returns None for anything malformed."""
    if msg.get("type") != "ticker":
        return None
    try:
        symbol = msg["product_id"]
        price = float(msg["price"])
        open_24h = float(msg["open_24h"])
        ts = datetime.fromisoformat(msg["time"].replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not isinstance(symbol, str) or not (math.isfinite(price) and price > 0):
        return None
    if not (math.isfinite(open_24h) and open_24h > 0):
        return None
    return Tick(symbol, price, open_24h, ts)


class Feed:
    """Streams ticks for `symbols` forever, reconnecting with exponential backoff.

    `status` is one of: connecting, live, reconnecting in Ns (reason).
    `last_msg` is the monotonic time of the last frame received (ticks or heartbeats).
    """

    def __init__(self, symbols: list[str], on_tick: Callable[[Tick], None],
                 on_status: Callable[[str], None] = lambda s: None, url: str = FEED_URL,
                 reconnect_after: float = RECONNECT_AFTER):
        self.symbols = list(symbols)
        self.on_tick = on_tick
        self.on_status = on_status
        self.url = url
        self.reconnect_after = reconnect_after
        self.last_msg = 0.0

    async def run(self):
        delay = 1
        while True:
            self.on_status("connecting")
            try:
                async with connect(self.url, ssl=SSL_CONTEXT if self.url.startswith("wss") else None,
                                   open_timeout=10) as ws:
                    await ws.send(json.dumps({"type": "subscribe", "product_ids": self.symbols,
                                              "channels": ["ticker", "heartbeat"]}))
                    live = False
                    while True:
                        # wait_for catches a half-open socket that never errors
                        msg = parse_message(await asyncio.wait_for(ws.recv(), self.reconnect_after))
                        if msg is None:
                            continue
                        if msg.get("type") == "error":
                            raise RuntimeError(str(msg.get("reason") or msg.get("message")))
                        tick = parse_tick(msg)
                        if tick or msg.get("type") == "heartbeat":
                            self.last_msg = time.monotonic()
                            if not live:
                                # only data proves the link works, so backoff resets here, not on connect
                                live, delay = True, 1
                                self.on_status("live")
                        if tick:
                            self.on_tick(tick)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network errors, closes, timeouts, server errors: all mean reconnect
                self.on_status(f"reconnecting in {delay}s ({str(e) or type(e).__name__})")
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
            delay = min(delay * 2, MAX_BACKOFF)
