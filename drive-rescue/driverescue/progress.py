"""Progress bar, rolling speed and slow-transfer detection."""
from __future__ import annotations

import shutil
import sys
import time
from collections import deque
from typing import Callable, Optional, TextIO

from .util import format_duration, human_bytes


class RollingRate:
    """Bytes per second over a sliding time window."""

    def __init__(self, window: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.window = window
        self.clock = clock
        self.samples: deque = deque()

    def add(self, total_done: float) -> None:
        now = self.clock()
        self.samples.append((now, total_done))
        cutoff = now - self.window
        while len(self.samples) > 2 and self.samples[1][0] <= cutoff:
            self.samples.popleft()

    def rate(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        (t0, d0), (t1, d1) = self.samples[0], self.samples[-1]
        return (d1 - d0) / (t1 - t0) if t1 > t0 else 0.0


def render_bar(fraction: float, width: int = 30) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


class Progress:
    """One-line live progress display (plain lines when not a terminal)."""

    def __init__(
        self,
        total: float,
        stream: Optional[TextIO] = None,
        interval: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.total = total
        self.stream = stream or sys.stdout
        self.clock = clock
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.interval = interval if self.tty else 10.0
        self.rate = RollingRate(30.0, clock)
        self._last = -1e9
        self._printed = False

    def format(self, done: float, note: str = "") -> str:
        fraction = done / self.total if self.total else 1.0
        speed = self.rate.rate()
        eta = (self.total - done) / speed if speed > 0 else None
        parts = [
            render_bar(fraction),
            f"{fraction * 100:5.1f}%",
            f"{human_bytes(done)}/{human_bytes(self.total)}",
            f"{human_bytes(speed)}/s",
            f"ETA {format_duration(eta)}",
        ]
        if note:
            parts.append(note)
        return " ".join(parts)

    def update(self, done: float, note: str = "") -> None:
        now = self.clock()
        self.rate.add(done)
        if now - self._last < self.interval and done < self.total:
            return
        self._last = now
        line = self.format(done, note)
        if self.tty:
            width = shutil.get_terminal_size((100, 20)).columns - 1
            self.stream.write("\r" + line[:width] + "\x1b[K")
        else:
            self.stream.write(line + "\n")
        self.stream.flush()
        self._printed = True

    def finish(self) -> None:
        if self.tty and self._printed:
            self.stream.write("\n")
            self.stream.flush()


class SlowWatcher:
    """Notices a transfer that stays below a speed threshold for a while."""

    def __init__(
        self,
        threshold_bps: float = 5e6,
        window: float = 120.0,
        cooldown: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.threshold = threshold_bps
        self.window = window
        self.cooldown = cooldown
        self.clock = clock
        self.rate = RollingRate(window, clock)
        self._first = None
        self._last_warned = -1e18

    def check(self, total_done: float) -> bool:
        """True when it has been slow for a full window and we should speak up."""
        now = self.clock()
        if self._first is None:
            self._first = now
        self.rate.add(total_done)
        if now - self._first < self.window:
            return False
        if self.rate.rate() >= self.threshold:
            return False
        if now - self._last_warned < self.cooldown:
            return False
        self._last_warned = now
        return True
