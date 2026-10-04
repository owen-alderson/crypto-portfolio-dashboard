"""Coinbase Exchange REST: candle history and product lookup (public, no API key)."""

import math
import time
from typing import NamedTuple

import httpx

REST_BASE = "https://api.exchange.coinbase.com"
MAX_CANDLES = 300  # Coinbase caps a request at 300 candles

# key -> (label, candle granularity in seconds): every granularity Coinbase offers
GRANULARITIES = {
    "1": ("1m", 60),
    "2": ("5m", 300),
    "3": ("15m", 900),
    "4": ("1h", 3600),
    "5": ("6h", 21600),
    "6": ("1d", 86400),
}


class Candle(NamedTuple):
    t: float  # bucket start, unix seconds
    o: float
    h: float
    l: float
    c: float
    v: float


async def fetch_candles(client: httpx.AsyncClient, symbol: str, granularity: int) -> list[Candle]:
    """Return the last MAX_CANDLES candles, oldest first. Raises httpx.HTTPError on network/HTTP failure."""
    end = int(time.time())
    resp = await client.get(f"{REST_BASE}/products/{symbol}/candles", params={
        "granularity": granularity, "start": end - MAX_CANDLES * granularity, "end": end,
    }, timeout=10)
    resp.raise_for_status()
    # rows are [time, low, high, open, close, volume], newest first; skip anything malformed
    rows = resp.json()
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            t, low, high, open_, close, volume = map(float, row[:6])
        except (TypeError, ValueError, KeyError):
            continue
        if all(map(math.isfinite, (t, low, high, open_, close, volume))):
            out.append(Candle(t, open_, high, low, close, volume))
    return sorted(out)


def apply_tick(candles: list[Candle], price: float, now: float, granularity: int):
    """Fold a live price into the last candle, or roll over to a new candle once `now` leaves its bucket."""
    bucket = now - now % granularity
    last = candles[-1]
    if bucket <= last.t:
        candles[-1] = last._replace(h=max(last.h, price), l=min(last.l, price), c=price)
    else:
        candles.append(Candle(bucket, price, price, price, price, 0.0))
        del candles[0]


async def product_exists(client: httpx.AsyncClient, symbol: str) -> bool:
    resp = await client.get(f"{REST_BASE}/products/{symbol}", timeout=10)
    if resp.status_code in (400, 404):
        return False
    resp.raise_for_status()
    return True
