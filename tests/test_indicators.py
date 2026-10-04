from pytest import approx

from crypto_terminal.history import Candle
from crypto_terminal.indicators import ema, rsi, sma, vwap

# StockCharts' worked RSI example (Wilder, 14 periods)
RSI_CLOSES = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826, 45.8931,
              46.0328, 45.614, 46.282, 46.282, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521,
              45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628, 43.1314]
RSI_EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
                41.87, 45.46, 37.30, 33.08, 37.77]


def test_sma():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2, 3, 4]
    assert sma([1, 2], 3) == [None, None]
    assert sma([], 3) == []


def test_ema():
    # seed = sma(2, 4, 6) = 4, k = 0.5: 0.5*8 + 0.5*4 = 6, then 0.5*4 + 0.5*6 = 5
    assert ema([2, 4, 6, 8, 4], 3) == [None, None, 4, 6, 5]
    assert ema([1, 2], 3) == [None, None]


def test_rsi_matches_reference():
    out = rsi(RSI_CLOSES)
    assert out[:14] == [None] * 14
    assert [round(x, 2) for x in out[14:]] == RSI_EXPECTED


def test_rsi_edges():
    assert rsi([1, 2, 3], 14) == [None] * 3
    assert rsi([1, 2, 3, 4], 2)[2:] == [100.0, 100.0]  # no losses
    assert rsi([4, 3, 2, 1], 2)[2:] == [0.0, 0.0]


def test_vwap_resets_each_utc_day():
    day = 86400
    candles = [
        Candle(day - 120, 0, 12, 6, 9, 1),   # typical 9
        Candle(day - 60, 0, 6, 0, 3, 2),     # typical 3 -> (9 + 6) / 3 = 5
        Candle(day, 0, 30, 0, 0, 0),         # new day, no volume yet
        Candle(day + 60, 0, 4, 1, 1, 4),     # typical 2
    ]
    assert vwap(candles) == [9, 5, None, approx(2)]
