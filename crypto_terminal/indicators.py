"""Chart indicators as pure functions. Each returns a list aligned with its input, None until there is enough data."""

DAY = 86400


def sma(values: list[float], n: int) -> list[float | None]:
    return [None] * min(n - 1, len(values)) + [sum(values[i - n:i]) / n for i in range(n, len(values) + 1)]


def ema(values: list[float], n: int) -> list[float | None]:
    """Seeded with the SMA of the first n values, then smoothed with k = 2 / (n + 1)."""
    if len(values) < n:
        return [None] * len(values)
    out, k = [None] * (n - 1) + [sum(values[:n]) / n], 2 / (n + 1)
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI: average gain / loss over n changes, then Wilder smoothing."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in deltas[:n]) / n
    loss = sum(max(-d, 0) for d in deltas[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            d = deltas[i - 1]
            gain, loss = (gain * (n - 1) + max(d, 0)) / n, (loss * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def vwap(candles) -> list[float | None]:
    """Volume-weighted typical price over candles (t, h, l, c, v), reset at each UTC day boundary."""
    out, day, pv, vol = [], None, 0.0, 0.0
    for c in candles:
        if c.t // DAY != day:
            day, pv, vol = c.t // DAY, 0.0, 0.0
        pv, vol = pv + (c.h + c.l + c.c) / 3 * c.v, vol + c.v
        out.append(pv / vol if vol else None)
    return out
