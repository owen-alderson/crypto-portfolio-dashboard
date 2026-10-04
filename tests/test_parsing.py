import json

import pytest

from terminal import app as app_module
from terminal.app import load_watchlist, parse_command, save_watchlist
from terminal.feed import parse_message, parse_tick
from terminal.widgets import sparkline

TICKER = {
    "type": "ticker", "product_id": "BTC-USD", "price": "85359.13", "open_24h": "84864.78",
    "time": "2026-10-04T12:07:17.878035Z",
}


def test_parse_tick_valid():
    tick = parse_tick(TICKER)
    assert tick.symbol == "BTC-USD"
    assert tick.price == 85359.13
    assert tick.open_24h == 84864.78
    assert tick.ts == pytest.approx(1791115637.878035)


@pytest.mark.parametrize("override", [
    {"type": "heartbeat"},
    {"price": None},
    {"price": "abc"},
    {"price": "NaN"},
    {"price": "-1"},
    {"open_24h": "0"},
    {"time": "yesterday"},
    {"time": 123},
    {"product_id": 7},
])
def test_parse_tick_rejects_malformed(override):
    assert parse_tick({**TICKER, **override}) is None


def test_parse_tick_rejects_missing_field():
    assert parse_tick({k: v for k, v in TICKER.items() if k != "price"}) is None


def test_parse_message():
    assert parse_message(json.dumps(TICKER)) == TICKER
    assert parse_message("not json") is None
    assert parse_message("[1, 2]") is None
    assert parse_message(b"\xff") is None


@pytest.mark.parametrize("text,expected", [
    ("add SOL-USD", ("add", "SOL-USD")),
    ("  ADD   sol-usd ", ("add", "SOL-USD")),
    ("rm ADA-USD", ("rm", "ADA-USD")),
    ("quit", ("quit", None)),
])
def test_parse_command_valid(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize("text", [
    "", "   ", "add", "add SOL-USD ETH-USD", "add SOL", "add ../../etc", "add SOL-USD?x=1",
    "rm", "buy BTC-USD", "quit now",
])
def test_parse_command_invalid(text):
    with pytest.raises(ValueError):
        parse_command(text)


def test_watchlist_roundtrip_and_bad_files(tmp_path, monkeypatch):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(app_module, "WATCHLIST_FILE", path)
    assert load_watchlist() == app_module.DEFAULT_WATCHLIST  # missing file
    save_watchlist(["BTC-USD", "DOGE-USD"])
    assert load_watchlist() == ["BTC-USD", "DOGE-USD"]
    path.write_text("{not json")
    assert load_watchlist() == app_module.DEFAULT_WATCHLIST
    path.write_text('["BTC-USD"]')
    assert load_watchlist() == app_module.DEFAULT_WATCHLIST
    path.write_text('{"symbols": ["BTC-USD", "BTC-USD", 5, "bad pair", "ETH-USD"]}')
    assert load_watchlist() == ["BTC-USD", "ETH-USD"]


def test_sparkline():
    assert sparkline([]) == ""
    assert sparkline([5, 5]) == "▁▁"
    assert sparkline([1, 2, 3]) == "▁▅█"
