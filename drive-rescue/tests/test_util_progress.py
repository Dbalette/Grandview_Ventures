import io
import unittest

from driverescue.progress import Progress, RollingRate, SlowWatcher, render_bar
from driverescue.util import format_duration, human_bytes


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FormattingTests(unittest.TestCase):
    def test_human_bytes_uses_decimal_units(self):
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(480103981056), "480.1 GB")
        self.assertEqual(human_bytes(2356 * 10**6), "2.4 GB")

    def test_format_duration(self):
        self.assertEqual(format_duration(None), "--")
        self.assertEqual(format_duration(12), "12s")
        self.assertEqual(format_duration(125), "2m 05s")
        self.assertEqual(format_duration(3 * 3600 + 5 * 60), "3h 05m")

    def test_render_bar_clamps(self):
        self.assertEqual(render_bar(0.5, 10), "[#####-----]")
        self.assertEqual(render_bar(2, 4), "[####]")
        self.assertEqual(render_bar(-1, 4), "[----]")


class RateTests(unittest.TestCase):
    def test_rolling_rate(self):
        clock = FakeClock()
        rate = RollingRate(window=10, clock=clock)
        rate.add(0)
        clock.t = 5
        rate.add(50)
        self.assertAlmostEqual(rate.rate(), 10.0)

    def test_progress_format_shows_percent_and_eta(self):
        clock = FakeClock()
        prog = Progress(1000, stream=io.StringIO(), clock=clock)
        prog.rate.add(0)
        clock.t = 10
        prog.rate.add(250)
        line = prog.format(250, "note")
        self.assertIn("25.0%", line)
        self.assertIn("ETA 30s", line)
        self.assertTrue(line.endswith("note"))

    def test_progress_writes_plain_lines_when_not_a_terminal(self):
        out = io.StringIO()
        prog = Progress(100, stream=out, clock=FakeClock())
        prog.update(100)
        self.assertIn("100.0%", out.getvalue())
        self.assertNotIn("\r", out.getvalue())


class SlowWatcherTests(unittest.TestCase):
    def test_warns_after_a_full_slow_window_then_waits(self):
        clock = FakeClock()
        watcher = SlowWatcher(threshold_bps=5e6, window=120, cooldown=600, clock=clock)
        done = 0
        warnings = []
        for second in range(0, 900, 10):
            clock.t = second
            done += 10 * 1e6  # 1 MB/s
            if watcher.check(done):
                warnings.append(second)
        self.assertEqual(warnings[0], 120)
        self.assertEqual(len(warnings), 2)  # again only after the cooldown
        self.assertGreaterEqual(warnings[1] - warnings[0], 600)

    def test_fast_transfer_never_warns(self):
        clock = FakeClock()
        watcher = SlowWatcher(threshold_bps=5e6, window=60, clock=clock)
        done = 0
        for second in range(0, 600, 10):
            clock.t = second
            done += 10 * 50e6
            self.assertFalse(watcher.check(done))


if __name__ == "__main__":
    unittest.main()
