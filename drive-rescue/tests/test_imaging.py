import errno
import os
import tempfile
import unittest

from driverescue.devices import Drive, Volume
from driverescue.imaging import BAD, FINISHED, NONTRIED, SUSPECT, Imager, RangeMap, open_image
from driverescue.safety import dest_on_source_drive, enough_space, permission_hint

MIB = 1024 * 1024


class SourceDevice:
    """Random data on a 'drive' where chosen byte ranges cannot be read."""

    def __init__(self, size, bad=(), flaky=None):
        self.data = os.urandom(size)
        self.size = size
        self.bad = list(bad)
        self.flaky = dict(flaky or {})  # block index (4096) -> failures left before it reads fine
        self.reads = 0

    def read_at(self, offset, length):
        self.reads += 1
        for start, end in self.bad:
            if offset < end and offset + length > start:
                raise OSError(errno.EIO, "Input/output error")
        blocks = range(offset // 4096, (offset + length - 1) // 4096 + 1)
        failing = [b for b in blocks if self.flaky.get(b, 0) > 0]
        if failing:
            for b in failing:
                self.flaky[b] -= 1
            raise OSError(errno.EIO, "Input/output error")
        return self.data[offset:offset + length]

    def expected_image(self, unreadable=()):
        out = bytearray(self.data)
        for start, end in unreadable:
            out[start:end] = bytes(end - start)
        return bytes(out)


class RangeMapTests(unittest.TestCase):
    def test_mark_splits_merges_and_totals(self):
        rmap = RangeMap(100)
        rmap.mark(0, 40, FINISHED)
        rmap.mark(40, 60, SUSPECT)
        rmap.mark(60, 100, FINISHED)
        rmap.mark(40, 50, FINISHED)
        self.assertEqual(rmap.ranges, [[0, 50, FINISHED], [50, 60, SUSPECT], [60, 100, FINISHED]])
        rmap.mark(50, 60, FINISHED)
        self.assertEqual(rmap.ranges, [[0, 100, FINISHED]])
        self.assertEqual(rmap.total(FINISHED), 100)
        self.assertEqual(rmap.spans(BAD), [])

    def test_save_load_and_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.json")
            rmap = RangeMap(100)
            rmap.mark(10, 20, BAD)
            rmap.save(path)
            self.assertEqual(RangeMap.load(path, 100).spans(BAD), [(10, 20)])
            with self.assertRaises(ValueError):
                RangeMap.load(path, 999)


class ImagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = os.path.join(self.tmp.name, "disk.img")
        self.map = os.path.join(self.tmp.name, "disk.map.json")

    def run_imager(self, dev, resume=False, **kwargs):
        fd = open_image(self.image, dev.size, resume)
        try:
            rmap = RangeMap.load(self.map, dev.size) if resume else RangeMap(dev.size)
            imager = Imager(dev.read_at, fd, rmap, chunk=MIB, map_path=self.map, **kwargs)
            return imager.run(), rmap
        finally:
            os.close(fd)

    def image_bytes(self):
        with open(self.image, "rb") as handle:
            return handle.read()

    def test_clean_drive_is_copied_exactly(self):
        dev = SourceDevice(4 * MIB)
        result, _ = self.run_imager(dev)
        self.assertTrue(result.complete)
        self.assertEqual((result.finished, result.bad), (4 * MIB, 0))
        self.assertEqual(self.image_bytes(), dev.data)

    def test_bad_blocks_cost_only_those_blocks(self):
        bad = (3 * MIB + 8192, 3 * MIB + 16384)
        dev = SourceDevice(8 * MIB, bad=[bad])
        result, rmap = self.run_imager(dev)
        self.assertTrue(result.complete)
        self.assertEqual(result.bad, 8192)
        self.assertEqual(result.finished, 8 * MIB - 8192)
        self.assertEqual(rmap.spans(BAD), [bad])
        self.assertEqual(self.image_bytes(), dev.expected_image([bad]))

    def test_long_bad_stretch_is_skipped_then_worked_through_gently(self):
        bad = (2 * MIB, 10 * MIB)
        dev = SourceDevice(12 * MIB, bad=[bad])
        result, _ = self.run_imager(dev)
        self.assertEqual(result.bad, 8 * MIB)
        self.assertEqual(result.finished, 4 * MIB)
        self.assertEqual(self.image_bytes(), dev.expected_image([bad]))

    def test_retry_pass_rescues_a_block_that_eventually_reads(self):
        flaky = {(MIB + 4096) // 4096: 30}
        result, _ = self.run_imager(SourceDevice(4 * MIB, flaky=dict(flaky)), retries=0)
        self.assertEqual(result.bad, 4096)
        os.unlink(self.image)
        dev = SourceDevice(4 * MIB, flaky=dict(flaky))
        result, _ = self.run_imager(dev, retries=40)
        self.assertEqual(result.bad, 0)
        self.assertEqual(self.image_bytes(), dev.data)

    def test_interrupted_image_resumes_where_it_stopped(self):
        dev = SourceDevice(8 * MIB, bad=[(5 * MIB, 5 * MIB + 4096)])
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 3

        result, _ = self.run_imager(dev, should_stop=stop)
        self.assertTrue(result.interrupted)
        self.assertFalse(result.complete)
        reads_before = dev.reads
        result, _ = self.run_imager(dev, resume=True)
        self.assertTrue(result.complete)
        self.assertEqual(result.bad, 4096)
        self.assertEqual(self.image_bytes(), dev.expected_image([(5 * MIB, 5 * MIB + 4096)]))
        self.assertLess(dev.reads - reads_before, 40)  # did not start over

    def test_open_image_never_overwrites(self):
        open(self.image, "wb").close()
        with self.assertRaises(FileExistsError):
            open_image(self.image, MIB, resume=False)
        with self.assertRaises(FileNotFoundError):
            open_image(os.path.join(self.tmp.name, "missing.img"), MIB, resume=True)


class SafetyTests(unittest.TestCase):
    def test_destination_on_the_source_drive_is_refused(self):
        with tempfile.TemporaryDirectory() as mount:
            drive = Drive("disk5", "/dev/disk5", volumes=[Volume("disk5s1", "Old", mount_point=mount)])
            self.assertIn("overwrite", dest_on_source_drive(os.path.join(mount, "sub", "x.img"), drive))
            self.assertIn("overwrite", dest_on_source_drive(os.path.join(mount, "x.img"), drive))
            with tempfile.TemporaryDirectory() as elsewhere:
                self.assertIsNone(dest_on_source_drive(os.path.join(elsewhere, "x.img"), drive))

    def test_enough_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, free = enough_space(os.path.join(tmp, "x.img"), 1)
            self.assertTrue(ok)
            self.assertFalse(enough_space(os.path.join(tmp, "x.img"), free + 10**9)[0])

    def test_permission_hints_match_the_two_macos_failure_modes(self):
        eperm = permission_hint(OSError(errno.EPERM, "Operation not permitted"), "macos", "scan disk5")
        self.assertIn("Full Disk Access", eperm)
        self.assertIn("Cmd+Q", eperm)
        eacces = permission_hint(OSError(errno.EACCES, "Permission denied"), "macos", "scan disk5")
        self.assertIn("sudo", eacces)
        self.assertIn("-m driverescue scan disk5", eacces)


if __name__ == "__main__":
    unittest.main()
