import errno
import unittest

from driverescue.scan import MIB, ScanReport, localize_bad, merge_ranges, run_scan


class FakeDevice:
    """A drive of zeros whose reads can fail or take a long (fake) time."""

    def __init__(self, size, bad=(), slow=(), clock=None):
        self.size = size
        self.bad = list(bad)
        self.slow = list(slow)
        self.clock = clock
        self.reads = 0

    def read_at(self, offset, length):
        self.reads += 1
        if self.clock:
            self.clock.t += 3.0 if any(s <= offset < e for s, e in self.slow) else 0.01
        for start, end in self.bad:
            if offset < end and offset + length > start:
                raise OSError(errno.EIO, "Input/output error")
        return bytes(length)


class FakeClock:
    t = 0.0

    def __call__(self):
        return self.t


class RangeHelperTests(unittest.TestCase):
    def test_merge_ranges(self):
        self.assertEqual(merge_ranges([[10, 20], [0, 5], [5, 8], [18, 30]]), [[0, 8], [10, 30]])

    def test_localize_finds_the_exact_blocks(self):
        dev = FakeDevice(8 * MIB, bad=[(3 * MIB + 8192, 3 * MIB + 20480)])
        found = localize_bad(dev.read_at, 0, 8 * MIB, 4096)
        self.assertEqual(found, [[3 * MIB + 8192, 3 * MIB + 20480]])


class ScanTests(unittest.TestCase):
    def test_clean_drive(self):
        clock = FakeClock()
        dev = FakeDevice(16 * MIB, clock=clock)
        rep = run_scan(dev.read_at, dev.size, chunk=MIB, clock=clock)
        self.assertTrue(rep.complete)
        self.assertEqual(rep.bytes_read, 16 * MIB)
        self.assertEqual(rep.bad_ranges, [])
        self.assertEqual(set(rep.heatmap()), {"#"})

    def test_unreadable_region_is_found_and_marked(self):
        dev = FakeDevice(16 * MIB, bad=[(10 * MIB + 8192, 10 * MIB + 20480)])
        rep = run_scan(dev.read_at, dev.size, chunk=MIB, min_block=4096)
        self.assertTrue(rep.complete)
        self.assertEqual(rep.bad_ranges, [[10 * MIB + 8192, 10 * MIB + 20480]])
        self.assertEqual(rep.bad_bytes, 12288)
        self.assertEqual(rep.heatmap().count("X"), 1)
        self.assertEqual(rep.bytes_read, 16 * MIB - 12288)  # everything except the unreadable blocks

    def test_slow_chunk_is_flagged(self):
        clock = FakeClock()
        dev = FakeDevice(32 * MIB, slow=[(20 * MIB, 21 * MIB)], clock=clock)
        rep = run_scan(dev.read_at, dev.size, chunk=MIB, clock=clock)
        self.assertEqual([c[0] for c in rep.slow_chunks], [20 * MIB])
        self.assertIn("~", rep.heatmap())

    def test_stop_then_resume_reads_each_byte_once(self):
        dev = FakeDevice(8 * MIB)
        count = {"n": 0}

        def stop():
            count["n"] += 1
            return count["n"] > 3

        rep = run_scan(dev.read_at, dev.size, chunk=MIB, should_stop=stop)
        self.assertFalse(rep.complete)
        self.assertEqual(rep.next_offset, 3 * MIB)
        restored = ScanReport.from_dict(rep.to_dict())
        rep = run_scan(dev.read_at, dev.size, chunk=MIB, report=restored)
        self.assertTrue(rep.complete)
        self.assertEqual(rep.bytes_read, 8 * MIB)
        self.assertEqual(dev.reads, 8)

    def test_permission_error_on_first_read_is_raised_not_reported_as_a_bad_drive(self):
        def denied(offset, length):
            raise OSError(errno.EPERM, "Operation not permitted")

        with self.assertRaises(OSError):
            run_scan(denied, 4 * MIB, chunk=MIB)

    def test_summary_mentions_unreadable_regions(self):
        dev = FakeDevice(4 * MIB, bad=[(MIB, MIB + 4096)])
        rep = run_scan(dev.read_at, dev.size, chunk=MIB, min_block=4096)
        text = "\n".join(rep.summary_lines())
        self.assertIn("Unreadable: 1 region(s), 4,096 bytes", text)


if __name__ == "__main__":
    unittest.main()
