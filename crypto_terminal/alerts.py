"""Price alerts: fire once when a pair reaches a level or moves a percentage from where the alert was set."""

import math
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .history import SYMBOL_RE
from .widgets import fmt_price

KINDS = (">", "<", "move")


@dataclass(frozen=True)
class Alert:
    symbol: str
    kind: str  # one of KINDS
    level: float  # price for > and <, percent for move
    ref: float | None = None  # move only: the price when the alert was set

    def __str__(self):
        if self.kind == "move":
            return f"{self.symbol} moves ±{self.level:g}% from {fmt_price(self.ref)}"
        return f"{self.symbol} {self.kind} {fmt_price(self.level)}"


def valid_level(kind: str, level: float) -> bool:
    # chained comparisons reject NaN, inf, zero and negatives
    return 0 < level < (100 if kind == "move" else math.inf)


def valid_alert(alert: Alert) -> bool:
    """Full check for alerts read back from disk (the file is user-editable)."""
    return (isinstance(alert.symbol, str) and bool(SYMBOL_RE.fullmatch(alert.symbol)) and alert.kind in KINDS
            and valid_level(alert.kind, alert.level)
            and (alert.kind != "move" or (alert.ref is not None and 0 < alert.ref < math.inf)))


def triggered(alert: Alert, price: float) -> bool:
    if alert.kind == ">":
        return price >= alert.level
    if alert.kind == "<":
        return price <= alert.level
    return abs(price - alert.ref) / alert.ref * 100 >= alert.level


def check(alerts: list[Alert], symbol: str, price: float) -> tuple[list[Alert], list[Alert]]:
    """Split alerts into (fired, remaining) for one tick."""
    fired = [a for a in alerts if a.symbol == symbol and triggered(a, price)]
    return fired, [a for a in alerts if a not in fired]


def desktop_notify(title: str, message: str):
    """Best effort: osascript on macOS, notify-send on Linux, silently skipped if neither exists."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        # text goes in as argv, never spliced into the script, so it can't inject AppleScript
        args = ["osascript", "-e", "on run argv", "-e",
                "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e", "end run", title, message]
    elif shutil.which("notify-send"):
        args = ["notify-send", "--", title, message]
    else:
        return
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
