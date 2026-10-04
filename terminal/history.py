"""Coinbase Exchange REST: candle history and product lookup (public, no API key)."""

import time

import httpx

REST_BASE = "https://api.exchange.coinbase.com"

# key -> (label, span in seconds, candle granularity in seconds); Coinbase caps a request at 300 candles
TIMEFRAMES = {
    "1": ("1h", 3600, 60),
    "2": ("1d", 86400, 300),
    "3": ("7d", 7 * 86400, 3600),
}


async def fetch_closes(client: httpx.AsyncClient, symbol: str, span: int, granularity: int) -> list[tuple[float, float]]:
    """Return [(unix_ts, close), ...] oldest first. Raises httpx.HTTPError on network/HTTP failure."""
    end = int(time.time())
    resp = await client.get(f"{REST_BASE}/products/{symbol}/candles", params={
        "granularity": granularity, "start": end - span, "end": end,
    }, timeout=10)
    resp.raise_for_status()
    # rows are [time, low, high, open, close, volume], newest first; skip anything malformed
    rows = resp.json()
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append((float(row[0]), float(row[4])))
        except (TypeError, ValueError, IndexError):
            continue
    return sorted(out)


async def product_exists(client: httpx.AsyncClient, symbol: str) -> bool:
    resp = await client.get(f"{REST_BASE}/products/{symbol}", timeout=10)
    if resp.status_code in (400, 404):
        return False
    resp.raise_for_status()
    return True
