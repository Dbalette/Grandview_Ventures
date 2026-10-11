import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mdr import remap, surface  # noqa: E402


class FakeDisk:
    """In-memory block device with a set of bad block indexes. Writes heal a block (like an SSD remap)."""

    def __init__(self, total_blocks: int, block_size: int, bad_blocks, unhealable=()):
        self.bs = block_size
        self.total = total_blocks * block_size
        self.bad = set(bad_blocks)
        self.unhealable = set(unhealable)
        self.reads = 0
        self.writes = 0

    def read(self, offset: int, length: int) -> bytes:
        self.reads += 1
        assert offset % self.bs == 0 and length % self.bs == 0, "unaligned read"
        for b in range(offset // self.bs, (offset + length) // self.bs):
            if b in self.bad:
                raise OSError(5, "Input/output error")
        return bytes(length)

    def write(self, offset: int, data: bytes) -> int:
        self.writes += 1
        b = offset // self.bs
        if b in self.unhealable:
            raise OSError(5, "Input/output error")
        self.bad.discard(b)
        return len(data)


class SurfaceScan(unittest.TestCase):
    def test_finds_exact_bad_blocks(self):
        disk = FakeDisk(total_blocks=4096, block_size=512, bad_blocks={10, 11, 1000, 4095})
        bm = surface.BadMap(device="/dev/rfake", block_size=512, total_bytes=disk.total)
        surface.scan(disk.read, bm, chunk_bytes=64 * 1024)
        self.assertTrue(bm.complete)
        self.assertEqual(bm.bad_blocks, 4)
        self.assertEqual(bm.bad_ranges, [[10 * 512, 1024], [1000 * 512, 512], [4095 * 512, 512]])
        self.assertEqual(bm.scanned_bytes, disk.total)
        self.assertTrue(bm.finished)

    def test_clean_disk(self):
        disk = FakeDisk(1024, 4096, set())
        bm = surface.BadMap(device="/dev/rfake", block_size=4096, total_bytes=disk.total)
        surface.scan(disk.read, bm, chunk_bytes=1 << 20)
        self.assertEqual(bm.bad_blocks, 0)
        self.assertEqual(bm.read_errors, 0)

    def test_resume_and_checkpoint(self):
        disk = FakeDisk(2048, 512, {1500})
        bm = surface.BadMap(device="/dev/rfake", block_size=512, total_bytes=disk.total)
        # First half only
        surface.scan(disk.read, bm, chunk_bytes=8192, end=disk.total // 2)
        self.assertFalse(bm.complete)
        self.assertEqual(bm.bad_blocks, 0)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bm.json")
            bm.save(path)
            bm2 = surface.BadMap.load(path)
        self.assertEqual(bm2.next_offset, disk.total // 2)
        surface.scan(disk.read, bm2, chunk_bytes=8192)
        self.assertTrue(bm2.complete)
        self.assertEqual(bm2.bad_ranges, [[1500 * 512, 512]])

    def test_merge_ranges(self):
        self.assertEqual(surface.merge_ranges([[0, 512], [512, 512], [3072, 512], [1024, 1024]]), [[0, 2048], [3072, 512]])
        self.assertEqual(surface.merge_ranges([]), [])


class Remap(unittest.TestCase):
    def test_zero_fill_heals(self):
        disk = FakeDisk(4096, 512, {10, 11, 1000})
        bm = surface.BadMap(device="/dev/rfake", block_size=512, total_bytes=disk.total)
        surface.scan(disk.read, bm, chunk_bytes=16384)
        self.assertEqual(bm.bad_blocks, 3)
        res = remap.zero_fill(disk.read, disk.write, bm, pad_blocks=0)
        self.assertEqual(res.attempted_blocks, 3)
        self.assertEqual(res.readable_after, 3)
        self.assertEqual(res.still_bad, 0)
        self.assertEqual(res.success_ratio, 1.0)

    def test_zero_fill_with_padding_and_unhealable(self):
        disk = FakeDisk(4096, 512, {100, 2000}, unhealable={2000})
        bm = surface.BadMap(device="/dev/rfake", block_size=512, total_bytes=disk.total, bad_ranges=[[100 * 512, 512], [2000 * 512, 512]])
        res = remap.zero_fill(disk.read, disk.write, bm, pad_blocks=1)
        self.assertEqual(res.attempted_blocks, 6)  # 99,100,101 and 1999,2000,2001
        self.assertEqual(res.write_failed_blocks, 1)
        self.assertEqual(res.still_bad, 1)
        self.assertEqual(res.still_bad_ranges, [[2000 * 512, 512]])

    def test_verify_ranges(self):
        disk = FakeDisk(64, 512, {5})
        good, bad = surface.verify_ranges(disk.read, [[4 * 512, 3 * 512]], 512)
        self.assertEqual(bad, [[5 * 512, 512]])
        self.assertEqual(good, [[4 * 512, 512], [6 * 512, 512]])


if __name__ == "__main__":
    unittest.main()
