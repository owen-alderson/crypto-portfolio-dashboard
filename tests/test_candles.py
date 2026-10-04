import httpx

from crypto_terminal.history import Candle, apply_tick, fetch_candles


async def test_fetch_candles_parses_and_skips_malformed_rows():
    rows = [
        [1_700_000_060, 9, 12, 10, 11, 5],    # newest first: [time, low, high, open, close, volume]
        [1_700_000_000, 8, 11, 9, 10, 4.5],
        [1_700_000_120, 9, 12],                # short
        "garbage", None, {"a": 1},
        [1_700_000_180, "x", 1, 1, 1, 1],      # not a number
        [1_700_000_240, 1, 1, 1, "NaN", 1],    # not finite
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=rows))
    async with httpx.AsyncClient(transport=transport) as client:
        candles = await fetch_candles(client, "BTC-USD", 60)
    assert candles == [Candle(1_700_000_000, 9, 11, 8, 10, 4.5), Candle(1_700_000_060, 10, 12, 9, 11, 5)]


async def test_fetch_candles_non_list_body():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"message": "NotFound"}))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await fetch_candles(client, "BTC-USD", 60) == []


def test_apply_tick_updates_current_candle():
    candles = [Candle(0, 1, 1, 1, 1, 1), Candle(60, 10, 11, 9, 10, 2)]
    apply_tick(candles, 12, now=119, granularity=60)
    assert candles[-1] == Candle(60, 10, 12, 9, 12, 2)
    apply_tick(candles, 8, now=100, granularity=60)
    assert candles[-1] == Candle(60, 10, 12, 8, 8, 2)
    assert len(candles) == 2


def test_apply_tick_rolls_over_to_new_candle():
    candles = [Candle(0, 1, 1, 1, 1, 1), Candle(60, 10, 11, 9, 10, 2)]
    apply_tick(candles, 13, now=125, granularity=60)
    assert candles == [Candle(60, 10, 11, 9, 10, 2), Candle(120, 13, 13, 13, 13, 0)]  # oldest dropped


def test_apply_tick_rolls_over_across_a_gap():
    candles = [Candle(60, 10, 11, 9, 10, 2)]
    apply_tick(candles, 5, now=3600 * 5 + 30, granularity=3600)
    assert candles == [Candle(18000, 5, 5, 5, 5, 0)]
