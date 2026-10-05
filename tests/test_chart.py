"""The text chart renderer: glyphs on exact half-rows, slots from time, honest axis labels, any terminal size."""

import random
import time
from datetime import datetime, timezone

from crypto_terminal.chart import (RSI_ROWS, TOO_SMALL, VOLUME_ROWS, fmt_price, half_row, nice_ticks, render,
                                   row_price)
from crypto_terminal.history import Candle
from crypto_terminal.indicators import ema, sma
from crypto_terminal.theme import GREEN, RED

T0 = 1_759_658_400  # 2025-10-05 10:00 UTC
FIXED = VOLUME_ROWS + 2  # rows below the price panel without RSI: separator, volume, time axis


def cells(line):
    """[(char, style)] for one rendered line."""
    styles = [""] * len(line.plain)
    for span in line.spans:
        styles[span.start:span.end] = [str(span.style)] * (span.end - span.start)
    return list(zip(line.plain, styles))


def column(lines, x, rows):
    """Characters down column x, grid and last-price line blanked."""
    return "".join(lines[r].plain[x] for r in rows).translate(str.maketrans("┄┆╌─", "    "))


def walk(n, granularity=60, seed=1, start=86_000.0):
    rng, p, out = random.Random(seed), start, []
    for i in range(n):
        o, c = p, p + rng.gauss(0, 40)
        out.append(Candle(T0 + i * granularity, o, max(o, c) + abs(rng.gauss(0, 20)),
                          min(o, c) - abs(rng.gauss(0, 20)), c, abs(rng.gauss(5, 3))))
        p = c
    return out


# 5 price rows = 10 half-rows over 109..100: half-row k is the price 109 - k
A = Candle(T0, 103.0, 109.0, 101.0, 106.0, 1.0)  # wick k0-k8, body k3-k6
DOJI = Candle(T0 + 60, 105.0, 105.0, 100.0, 105.0, 1.0)  # body k4 only, wick down to k9
ROWS = 5


def small_chart(candles=(A, DOJI), **kw):
    return render(list(candles), 60, 9 + 4, ROWS + FIXED, 2, **kw)  # axis 6 + 3 wide: 2 slots of 2 columns


def test_glyphs_land_on_their_half_rows():
    lines = small_chart()
    assert half_row(109, 109, 100, ROWS) == 0 and half_row(100, 109, 100, ROWS) == 2 * ROWS - 1
    # wick+wick, wick+body (body starts mid-row), body+body, body+wick, wick+empty (low mid-row)
    assert column(lines, 0, range(ROWS)) == "│▄█▀╵"
    # doji: a one-half-row body on k4, then wick to the bottom half-row
    assert column(lines, 2, range(ROWS)) == "  ▀││"
    assert all(cells(lines[r])[0][1] == GREEN for r in range(ROWS))


def test_red_candle_and_its_volume_take_red():
    down = Candle(T0 + 60, 105.0, 105.0, 100.0, 102.0, 1.0)
    lines = small_chart((A, down))
    assert cells(lines[2])[2] == ("█", RED)
    assert cells(lines[ROWS + VOLUME_ROWS])[2][1] != cells(lines[ROWS + VOLUME_ROWS])[0][1]


def test_scale_has_no_padding_and_ignores_out_of_range_overlays():
    plain = render([A, DOJI], 60, 13, ROWS + FIXED + 1, 2, show_rsi=False,
                   overlays=[("X", "yellow", [None, None])])  # legend row, nothing to draw
    wild = render([A, DOJI], 60, 13, ROWS + FIXED + 1, 2, overlays=[("X", "yellow", [500.0, 1.0])])
    assert [line.plain for line in plain] == [line.plain for line in wild]
    inside = render([A, DOJI], 60, 13, ROWS + FIXED + 1, 2, overlays=[("X", "yellow", [None, 108.0])])
    assert inside[1 + 0].plain[2:4] == "⣀⣀"  # 108 = k1: bottom half of the first price row, across the slot


def test_axis_labels_are_the_exact_price_of_their_line():
    candles = walk(300)
    rows, width = 40 - FIXED, 120
    lines = render(candles, 60, width, 40, 2)
    label_w = len(fmt_price(max(c.h for c in candles)))
    plot_w = width - label_w - 3
    shown = candles[-(plot_w // 2):]
    hi, lo = max(c.h for c in shown), min(c.l for c in shown)
    labelled = [r for r in range(rows) if lines[r].plain[plot_w + 2:].strip()
                and "black" not in cells(lines[r])[plot_w + 2][1]]
    assert len(labelled) >= 3
    for r in labelled:
        price = row_price(r, hi, lo, rows)
        assert lines[r].plain[plot_w + 2:].strip() == fmt_price(price)
        assert "┄" in lines[r].plain[:plot_w]  # on a grid line
        step = (hi - lo) / (2 * rows - 1)  # the line is exactly where the row's top half meets its bottom half
        assert half_row(price + step / 100, hi, lo, rows) == 2 * r
        assert half_row(price - step / 100, hi, lo, rows) == 2 * r + 1


def test_last_price_tag_sits_on_the_close_row():
    candles = walk(100)
    rows, width = 30 - FIXED, 100
    lines = render(candles, 60, width, 30, 2)
    shown = candles[-((width - 12) // 2):]
    hi, lo = max(c.h for c in shown), min(c.l for c in shown)
    tagged = [r for r in range(30) if "black on" in "".join(s for _, s in cells(lines[r]))]
    assert tagged == [half_row(candles[-1].c, hi, lo, rows) // 2]
    colour = GREEN if candles[-1].c >= candles[-1].o else RED
    assert lines[tagged[0]].plain[-10:].strip() == fmt_price(candles[-1].c)
    assert cells(lines[tagged[0]])[-2][1] == f"black on {colour}"


def test_missing_candle_leaves_an_empty_slot():
    candles = [Candle(T0 + i * 60, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1.0) for i in (0, 1, 3)]
    lines = render(candles, 60, 9 + 8, 30, 2)  # 4 slots: columns 0, 2, 4, 6
    body = range(30 - FIXED)
    assert column(lines, 4, body).strip() == ""  # minute 2 is missing
    assert all(column(lines, x, body).strip() for x in (0, 2, 6))
    assert lines[30 - 2].plain[4] == " " and lines[30 - 2].plain[6] == "█"  # volume too


def test_time_labels_start_at_their_candles_column():
    candles = [c._replace(v=1.0 if c.t % 300 == 0 else 0.0) for c in walk(300)]  # bars only every 5 minutes
    for slot in (1, 2, 4):
        lines = render(candles, 60, 150, 30, slot)
        plot_w = 150 - len(fmt_price(max(c.h for c in candles))) - 3
        n, body = plot_w // slot, max(1, slot - 1)
        x0 = plot_w - n * slot
        labels = [(i, w) for i, w in enumerate(lines[-1].plain) if w != " " and (i == 0 or lines[-1].plain[i - 1] == " ")]
        assert len(labels) >= 2
        bars = lines[-2].plain
        for x, _ in labels:
            text = lines[-1].plain[x:x + 5]
            t = datetime.strptime(f"2025-10-05 {text}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
            s = n - 1 - int((candles[-1].t - t) // 60)
            assert x == x0 + s * slot + body // 2  # the candle's wick column
            assert bars[x] == "█" and bars[x0 + s * slot:x0 + s * slot + body] == "█" * body


def test_slot_width_sets_the_visible_count():
    candles = walk(300)
    label_w = len(fmt_price(max(c.h for c in candles)))
    for slot in (1, 2, 4):
        lines = render([c._replace(v=1.0) for c in candles], 60, 120, 30, slot)
        assert lines[-2].plain.count("█") == (120 - label_w - 3) // slot * max(1, slot - 1)


def test_doji_flat_and_single_candle_render():
    flat = Candle(T0, 5.0, 5.0, 5.0, 5.0, 0.0)  # hi == lo, no volume
    lines = render([flat], 60, 40, 20, 4)
    assert len(lines) == 20 and all(line.cell_len == 40 for line in lines)
    assert sum(line.plain.count("▀") + line.plain.count("▄") for line in lines) == 3  # one half-row, 3 wide
    assert any("5.0000" in line.plain for line in lines)


def test_fewer_candles_than_the_window():
    lines = render(walk(3), 60, 120, 30, 2, overlays=[("SMA 20", "yellow", [None] * 3)], show_rsi=True)
    assert len(lines) == 30 and all(line.cell_len == 120 for line in lines)
    assert lines[0].plain.split() == ["SMA", "20", "RSI", "14"]


def test_rsi_guides_sit_exactly_on_70_and_30():
    for level, row in ((70, 2), (30, 5)):
        assert half_row(level, 100, 0, RSI_ROWS) // 2 == row
        assert row_price(row, 100, 0, RSI_ROWS) == level  # mid-row: above the line is above the level
    lines = render(walk(100), 60, 100, 40, 2, show_rsi=True)
    rsi_top = 40 - 1 - RSI_ROWS
    assert lines[rsi_top + 2].plain.rstrip().endswith("70") and lines[rsi_top + 5].plain.rstrip().endswith("30")


def test_nice_ticks():
    assert nice_ticks(100, 109, 4) == [100, 102.5, 105, 107.5]
    assert nice_ticks(5, 5, 4) == [5]
    assert all(len(nice_ticks(0, x, 5)) <= 6 for x in (0.001, 1, 7, 13, 999, 86_000))


def test_any_size_renders_without_crashing():
    candles = walk(300)
    overlays = [("SMA 20", "yellow", sma([c.c for c in candles], 20))]
    for width in (0, 1, 2, 5, 11, 12, 13, 14, 20, 41, 80):
        for height in (0, 1, 5, 11, 12, 13, 21, 22, 23, 40):
            for slot in (1, 2, 4):
                for kw in ({}, {"overlays": overlays, "show_rsi": True}):
                    lines = render(candles, 60, width, height, slot, **kw)
                    assert len(lines) <= height and all(line.cell_len <= width for line in lines)
                    if lines and lines[0].plain != TOO_SMALL[:width]:
                        assert len(lines) == height and all(line.cell_len == width for line in lines)


def test_render_is_fast():
    candles = walk(300)
    closes = [c.c for c in candles]
    overlays = [("SMA 20", "yellow", sma(closes, 20)), ("EMA 50", "cyan", ema(closes, 50))]
    best = min(_timed(lambda: render(candles, 60, 200, 50, 1, overlays, True)) for _ in range(5))
    assert best < 0.020


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start
