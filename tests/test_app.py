"""Headless UI tests (Textual Pilot) with the network stubbed out."""

import asyncio
import json
import time

import pytest

from terminal import app as app_module
from terminal.app import TerminalApp
from terminal.feed import Tick
from terminal.widgets import PriceTable


class FakeFeed:
    instances = []

    def __init__(self, symbols, on_tick, on_status):
        self.symbols, self.on_tick, self.on_status, self.last_msg = symbols, on_tick, on_status, 0.0
        FakeFeed.instances.append(self)

    async def run(self):
        self.last_msg = time.monotonic()
        self.on_status("live")
        await asyncio.Event().wait()


@pytest.fixture
def offline(tmp_path, monkeypatch):
    FakeFeed.instances = []
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(app_module, "WATCHLIST_FILE", path)
    monkeypatch.setattr(app_module, "Feed", FakeFeed)

    async def fake_exists(client, symbol):
        return symbol == "DOGE-USD"

    async def fake_closes(client, symbol, span, granularity):
        return [(1_700_000_000 + i * granularity, 100.0 + i) for i in range(10)]

    monkeypatch.setattr(app_module, "product_exists", fake_exists)
    monkeypatch.setattr(app_module, "fetch_closes", fake_closes)
    return path


async def type_command(pilot, text):
    await pilot.press("slash")
    await pilot.press(*text)
    await pilot.press("enter")
    await pilot.pause(0.2)


async def test_ticks_update_table(offline):
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        feed = FakeFeed.instances[-1]
        assert feed.symbols == app_module.DEFAULT_WATCHLIST
        feed.on_tick(Tick("BTC-USD", 100.0, 90.0, 0))
        feed.on_tick(Tick("BTC-USD", 101.0, 90.0, 0))
        table = app.query_one(PriceTable)
        last = table.get_cell("BTC-USD", "last")
        assert last.plain == "101.0000" and "green" in str(last.style)
        assert table.get_cell("BTC-USD", "chg").plain == "▲ +12.22%"
        await pilot.pause(0.7)  # flash wears off, colour stays
        assert "on green" not in str(table.get_cell("BTC-USD", "last").style)


async def test_add_remove_persist(offline):
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await type_command(pilot, "add DOGE-USD")
        assert app.symbols[-1] == "DOGE-USD"
        assert FakeFeed.instances[-1].symbols[-1] == "DOGE-USD"  # feed restarted with the new list
        await type_command(pilot, "rm ADA-USD")
        assert "ADA-USD" not in app.symbols
        assert app.query_one(PriceTable).row_count == 5
    saved = json.loads(offline.read_text())["symbols"]
    assert saved == ["BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD", "DOGE-USD"]

    app = TerminalApp()  # restart: list comes back from disk
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.symbols == saved


async def test_bad_commands_notify_and_do_not_crash(offline):
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        messages = set()  # collected as we go: toasts expire after a few seconds
        for text in ("add FAKE-USD", "add nonsense", "rm DOGE-USD", "launch rockets", "add BTC-USD"):
            await type_command(pilot, text)
            messages |= {n.message for n in app._notifications}
        assert app.symbols == app_module.DEFAULT_WATCHLIST
        assert "unknown pair: FAKE-USD" in messages
        assert any(m.startswith("not a pair: nonsense") for m in messages)
        assert "DOGE-USD is not on the watchlist" in messages
        assert not offline.exists()  # nothing changed, nothing written


async def test_keys_in_command_bar_do_not_trigger_bindings(offline):
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash", "1")
        assert app.timeframe == "2"
        await pilot.press("escape")
        await pilot.press("3")
        assert app.timeframe == "3"


async def test_stale_status(offline):
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one("#status")
        assert "LIVE" in str(status.render())
        app.feed.last_msg = 0.0  # no frame for a long time
        app.refresh_status()
        assert "STALE" in str(status.render())


async def test_empty_watchlist_stops_feed(offline):
    offline.write_text('{"symbols": ["BTC-USD"]}')
    app = TerminalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await type_command(pilot, "rm BTC-USD")
        assert app.symbols == [] and app.feed is None
        assert "IDLE" in str(app.query_one("#status").render())
